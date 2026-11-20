"""Builds activity sequences from concepts, runs downtime simulation, schedules and costs."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import numpy as np

from .models import (Concept, ConceptResult, PackageResult, Project, ProjectResult,
                     WorkPackage, Coord)
from . import abpmer, rpl
from .weather import SeqStep, get_engine

NM_PER_KM = 1 / 1.852


def distance_nm(a: Coord, b: Coord) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h)) * NM_PER_KM


def _nm(a: tuple, b: tuple) -> float:
    return rpl.haversine_m(a[0], a[1], b[0], b[1]) / 1852


def build_sequence(pkg: WorkPackage, vessel, port: Coord, site: Coord,
                   cables: list[dict] | None = None,
                   trips_limit: int | None = None) -> tuple[list[SeqStep], int]:
    """Expand a work package into its full activity list (Pnet, no weather).

    With an RPL (`cables`), each unit is one cable: steps sit at the cable's first or second
    end, rate-based steps (e.g. freelay m/h) scale with route length, transits go to/from the
    actual cable ends, and infield moves use the distance between consecutive cables.
    `trips_limit=1` returns a single trip cycle (ABPmer 'repeat N times' export).
    """
    pt = (port.lat, port.lon)
    if cables:
        units = [(c["id"], tuple(c["start"]), tuple(c["end"]), c["length_m"]) for c in cables]
    else:
        units = [(f"U{i+1}", (site.lat, site.lon), (site.lat, site.lon), None) for i in range(pkg.quantity)]
    steps: list[SeqStep] = []
    cap = max(1, vessel.deck_capacity)
    trips = math.ceil(len(units) / cap)
    tl = pkg.transit_limits
    f = pkg.contingency_factor

    def mk(name, step_or_dur, limits, where, pos):
        if isinstance(step_or_dur, (int, float)):
            d, win, grp, day = float(step_or_dur), None, False, False
        else:
            d, win, grp, day = (step_or_dur.duration_h, step_or_dur.window_h,
                                step_or_dur.group_with_next, step_or_dur.daylight_only)
        return SeqStep(name, d, limits.hs_max, limits.ws_max, where,
                       win if win is not None else d * f, limits.uc_max, grp, day, pos[0], pos[1])

    def install_duration(s, length_m):
        if s.rate_m_per_h and length_m:
            return length_m / s.rate_m_per_h
        return s.duration_h

    n_trips = trips if trips_limit is None else min(trips, trips_limit)
    for trip in range(n_trips):
        batch = units[trip * cap:(trip + 1) * cap]
        for uid, *_ in batch:
            for s in pkg.load_steps:
                steps.append(mk(f"T{trip+1} {uid} load {s.name}", s, s.limits, "port", pt))
        out_h = _nm(pt, batch[0][1]) / vessel.transit_speed_kn
        steps.append(mk(f"T{trip+1} transit to site", out_h, tl, "transit", pt))
        prev_end = None
        for uid, start, end, length in batch:
            if prev_end is not None:
                move_h = (_nm(prev_end, start) / pkg.infield_speed_kn) if cables else pkg.infield_move_h
                if move_h > 0:
                    steps.append(mk(f"T{trip+1} move to {uid}", move_h, tl, "transit", prev_end))
            for s in pkg.install_steps:
                d = install_duration(s, length)
                win = s.window_h if (s.window_h is not None and not (s.rate_m_per_h and length)) else d * f
                step = s.model_copy(update={"duration_h": d, "window_h": win})
                label = f"{s.name} (@ {s.rate_m_per_h:g} m/h)" if (s.rate_m_per_h and length) else s.name
                steps.append(mk(f"T{trip+1} {uid} {label}", step, s.limits, "site",
                                end if s.position == "end" else start))
            prev_end = end
        back_h = _nm(prev_end, pt) / vessel.transit_speed_kn
        steps.append(mk(f"T{trip+1} transit to port", back_h, tl, "transit", prev_end))
    return steps, trips


def _order(packages: list[WorkPackage]) -> list[WorkPackage]:
    by_id = {p.id: p for p in packages}
    done, out = set(), []

    def visit(p, stack=()):
        if p.id in done:
            return
        if p.id in stack:
            raise ValueError(f"Circular dependency at package '{p.id}'")
        if p.after:
            if p.after not in by_id:
                raise ValueError(f"Package '{p.id}' follows unknown package '{p.after}'")
            visit(by_id[p.after], stack + (p.id,))
        done.add(p.id)
        out.append(p)

    for p in packages:
        visit(p)
    return out


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def run_concept(project: Project, concept: Concept) -> ConceptResult:
    ports = {p.name: p for p in concept.ports}
    vessels = {v.name: v for v in concept.vessels}
    engine = get_engine(project.weather, project.site.lat, project.site.lon, project.hindcast_years)
    pct = project.percentile

    finish: dict[str, datetime] = {}
    warnings: list[str] = []
    results: list[PackageResult] = []
    breakdown: dict[str, float] = {}

    for pkg in _order(concept.packages):
        if pkg.vessel not in vessels:
            raise ValueError(f"{concept.name}: package '{pkg.id}' uses unknown vessel '{pkg.vessel}'")
        if pkg.port not in ports:
            raise ValueError(f"{concept.name}: package '{pkg.id}' uses unknown port '{pkg.port}'")
        v, port = vessels[pkg.vessel], ports[pkg.port]
        candidates = []
        if pkg.start_date:
            candidates.append(datetime.combine(pkg.start_date, datetime.min.time()))
        if pkg.after:
            candidates.append(finish[pkg.after] + timedelta(days=pkg.lag_days))
        if not candidates:
            raise ValueError(f"{concept.name}: package '{pkg.id}' needs start_date or after")
        start = max(candidates)

        nm = distance_nm(port.location, project.site)
        cables = rpl.load_rpl(pkg.rpl) if pkg.rpl else None
        if cables and pkg.quantity != len(cables):
            warnings.append(f"{pkg.name}: quantity {pkg.quantity} replaced by {len(cables)} cables from the RPL.")
        steps, trips = build_sequence(pkg, v, port.location, project.site, cables)
        net_h = sum(s.duration_h for s in steps)
        if pkg.abpmer_result:
            table = abpmer.load_result(pkg.abpmer_result)
            p10, p50, p90 = (abpmer.lookup_hours(table, start.date(), q) for q in (10, pct, 90))
            source = f"ABPmer: {table['operation']}"
            if net_h > 0 and abs(table["net_days"] * 24 - net_h) / net_h > 0.10:
                warnings.append(
                    f"{pkg.name}: ABPmer net duration {table['net_days']:.1f} d differs from the planner's "
                    f"Pnet {net_h / 24:.1f} d by more than 10% - check the result matches this package.")
        else:
            hours = engine.simulate(steps, start.date(), project.hindcast_years)
            if not np.all(np.isfinite(hours)):
                raise ValueError(f"{concept.name}: '{pkg.name}' never finds a weather window - check limits")
            p10, p50, p90 = (float(np.percentile(hours, q)) for q in (10, pct, 90))
            source = "simulation"
            if any(s.uc_max is not None for s in steps) and engine.name.startswith("synthetic"):
                warnings.append(f"{pkg.name}: current limits (Uc) are ignored by the synthetic hindcast.")
        end = start + timedelta(hours=p50)
        finish[pkg.id] = end
        days = p50 / 24

        cost = v.day_rate_eur * days                     # MVP CAPEX: vessel day rate x P50 duration
        breakdown[pkg.component] = breakdown.get(pkg.component, 0.0) + cost

        results.append(PackageResult(
            id=pkg.id, name=pkg.name, component=pkg.component, vessel=v.name, port=port.name,
            quantity=len(cables) if cables else pkg.quantity, trips=trips,
            route_km=round(sum(c["length_m"] for c in cables) / 1000, 1) if cables else None, transit_nm=round(nm, 1),
            net_duration_days=round(net_h / 24, 1), start=_fmt(start), p50_end=_fmt(end),
            p10_days=round(p10 / 24, 1), p50_days=round(days, 1), p90_days=round(p90 / 24, 1),
            weather_downtime_pct=round(100 * (1 - net_h / p50), 1) if p50 > 0 else 0.0,
            downtime_source=source,
            day_rate_eur=v.day_rate_eur,
            cost_eur=round(cost),
        ))

    c_start = min(datetime.fromisoformat(r.start) for r in results)
    c_end = max(finish.values())
    return ConceptResult(
        name=concept.name, description=concept.description,
        start=_fmt(c_start), p50_end=_fmt(c_end),
        p50_total_days=round((c_end - c_start).total_seconds() / 86400, 1),
        total_cost_eur=round(sum(breakdown.values())),
        cost_breakdown_eur={k: round(val) for k, val in breakdown.items()},
        packages=results,
        warnings=sorted(set(warnings)),
    )


def run_project(project: Project) -> ProjectResult:
    engine = get_engine(project.weather, project.site.lat, project.site.lon, project.hindcast_years)
    return ProjectResult(
        project=project.name, weather_provider=engine.name, percentile=project.percentile,
        concepts=[run_concept(project, c) for c in project.concepts],
    )
