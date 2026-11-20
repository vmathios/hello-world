"""Builds activity sequences from concepts, runs downtime simulation, schedules and costs."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import numpy as np

from .models import (Concept, ConceptResult, PackageResult, Project, ProjectResult,
                     WorkPackage, Coord)
from . import abpmer
from .weather import SeqStep, get_engine

NM_PER_KM = 1 / 1.852


def distance_nm(a: Coord, b: Coord) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h)) * NM_PER_KM


def build_sequence(pkg: WorkPackage, vessel, transit_nm: float,
                   port: Coord | None = None, site: Coord | None = None,
                   trips_limit: int | None = None) -> tuple[list[SeqStep], int]:
    """Expand a work package into its full activity list (Pnet, no weather).

    `trips_limit=1` returns a single trip cycle (used for the ABPmer 'repeat N times' export).
    """
    steps: list[SeqStep] = []
    cap = max(1, vessel.deck_capacity)
    trips = math.ceil(pkg.quantity / cap)
    transit_h = transit_nm / vessel.transit_speed_kn
    tl = pkg.transit_limits
    f = pkg.contingency_factor
    plat, plon = (port.lat, port.lon) if port else (None, None)
    slat, slon = (site.lat, site.lon) if site else (None, None)

    def mk(name, step_or_dur, limits, where, lat, lon):
        if isinstance(step_or_dur, (int, float)):
            d, win, grp, day = float(step_or_dur), None, False, False
        else:
            d, win, grp, day = (step_or_dur.duration_h, step_or_dur.window_h,
                                step_or_dur.group_with_next, step_or_dur.daylight_only)
        return SeqStep(name, d, limits.hs_max, limits.ws_max, where,
                       win if win is not None else d * f, limits.uc_max, grp, day, lat, lon)

    remaining = pkg.quantity
    for trip in range(trips if trips_limit is None else min(trips, trips_limit)):
        units = min(cap, remaining)
        remaining -= units
        for u in range(units):
            for s in pkg.load_steps:
                steps.append(mk(f"T{trip+1} load {s.name}", s, s.limits, "port", plat, plon))
        steps.append(mk(f"T{trip+1} transit to site", transit_h, tl, "transit", plat, plon))
        for u in range(units):
            if u > 0 and pkg.infield_move_h > 0:
                steps.append(mk(f"T{trip+1} move to next location", pkg.infield_move_h, tl, "transit", slat, slon))
            for s in pkg.install_steps:
                steps.append(mk(f"T{trip+1} U{u+1} {s.name}", s, s.limits, "site", slat, slon))
        steps.append(mk(f"T{trip+1} transit to port", transit_h, tl, "transit", slat, slon))
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
    used_ports, used_vessels = set(), set()
    breakdown = {"Vessel spread": 0.0, "Mob/demob": 0.0, "Port": 0.0, "Other": 0.0}

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
        steps, trips = build_sequence(pkg, v, nm, port.location, project.site)
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

        cost = {
            "Vessel spread": v.day_rate_eur * days,
            "Mob/demob": 0.0 if v.name in used_vessels else v.mob_demob_eur,
            "Port": port.day_rate_eur * days + (0.0 if port.name in used_ports else port.fixed_cost_eur),
            "Other": pkg.extra_costs_eur,
        }
        used_vessels.add(v.name)
        used_ports.add(port.name)
        for k, val in cost.items():
            breakdown[k] += val

        results.append(PackageResult(
            id=pkg.id, name=pkg.name, component=pkg.component, vessel=v.name, port=port.name,
            quantity=pkg.quantity, trips=trips, transit_nm=round(nm, 1),
            net_duration_days=round(net_h / 24, 1), start=_fmt(start), p50_end=_fmt(end),
            p10_days=round(p10 / 24, 1), p50_days=round(days, 1), p90_days=round(p90 / 24, 1),
            weather_downtime_pct=round(100 * (1 - net_h / p50), 1) if p50 > 0 else 0.0,
            downtime_source=source,
            cost_eur={k: round(val) for k, val in cost.items()},
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
