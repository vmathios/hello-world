"""Weather downtime engines.

Every engine answers one question: given an ordered sequence of non-splittable
weather-limited steps and a start date, how many hours does the sequence take,
for each year of the hindcast?  The planner then takes P10/P50/P90 of that.

* HindcastEngine   - built-in sequential persistence simulation over an hourly
                     Hs / wind time series (synthetic or loaded from CSV).
* ExternalEngine   - adapter for a third-party downtime tool exposed over HTTP.
                     Fill in `_to_payload` / `_from_response` to match its API.
"""
from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass
from datetime import date
from typing import Optional, Protocol

import numpy as np

HOURS_PER_YEAR = 8760


@dataclass(frozen=True)
class SeqStep:
    name: str
    duration_h: float
    hs_max: Optional[float] = None
    ws_max: Optional[float] = None
    where: str = "site"      # "port" | "transit" | "site"


class DowntimeEngine(Protocol):
    name: str

    def simulate(self, steps: list[SeqStep], start: date, years: int) -> np.ndarray:
        """Return elapsed hours (incl. weather waiting) for each hindcast year."""
        ...


# --------------------------------------------------------------------------
# Built-in hindcast engine
# --------------------------------------------------------------------------

class HindcastEngine:
    def __init__(self, hs: np.ndarray, ws: np.ndarray, name: str = "hindcast"):
        assert hs.shape == ws.shape
        n_years = len(hs) // HOURS_PER_YEAR
        if n_years < 1:
            raise ValueError("Need at least one full year of hourly hindcast")
        n = n_years * HOURS_PER_YEAR
        # Circular extension so campaigns starting late in the last year can run on.
        self.hs = np.concatenate([hs[:n], hs[:n]])
        self.ws = np.concatenate([ws[:n], ws[:n]])
        self.n_years = n_years
        self.name = name
        self._cache: dict[tuple, np.ndarray] = {}

    def _feasible_starts(self, hs_max, ws_max, d: int) -> np.ndarray:
        key = (hs_max, ws_max, d)
        if key not in self._cache:
            ok = np.ones(len(self.hs), dtype=bool)
            if hs_max is not None:
                ok &= self.hs <= hs_max
            if ws_max is not None:
                ok &= self.ws <= ws_max
            n = len(ok)
            idx = np.arange(n)
            pos = np.where(~ok, idx, n)
            next_bad = np.minimum.accumulate(pos[::-1])[::-1]
            run = next_bad - idx          # consecutive workable hours from t
            self._cache[key] = np.flatnonzero(run >= d)
        return self._cache[key]

    def run_once(self, steps: list[SeqStep], t0: int) -> float:
        t = t0
        for s in steps:
            d = max(1, math.ceil(s.duration_h))
            if s.hs_max is None and s.ws_max is None:
                t += d
                continue
            feas = self._feasible_starts(s.hs_max, s.ws_max, d)
            k = np.searchsorted(feas, t)
            if k >= len(feas):
                return math.inf          # never a window - limits too strict
            t = int(feas[k]) + d
        return float(t - t0)

    def simulate(self, steps: list[SeqStep], start: date, years: int) -> np.ndarray:
        doy = min(start.timetuple().tm_yday - 1, 364)
        ys = range(min(years, self.n_years))
        return np.array([self.run_once(steps, y * HOURS_PER_YEAR + doy * 24) for y in ys])


def synthetic_hindcast(lat: float, lon: float, years: int = 20, seed: Optional[int] = None):
    """Statistically North-Sea-like hourly Hs / Ws (for demos - replace with real data).

    Seasonal log-normal Hs with AR(1) persistence (~3 day decorrelation), wind
    correlated with Hs. Mean Hs ~1.5 m winter-weighted.
    """
    if seed is None:
        seed = int(abs(lat * 1000) + abs(lon * 1000))
    rng = np.random.default_rng(seed)
    n = years * HOURS_PER_YEAR
    t = np.arange(n)
    doy = (t // 24) % 365
    season = np.cos(2 * np.pi * (doy - 15) / 365)        # +1 mid-Jan, -1 mid-Jul
    mean_hs = 1.45 + 0.6 * season
    sigma = 0.55
    phi = 0.985
    e = rng.standard_normal(n) * math.sqrt(1 - phi ** 2)
    z = np.empty(n)
    z[0] = e[0]
    for i in range(1, n):
        z[i] = phi * z[i - 1] + e[i]
    hs = mean_hs * np.exp(sigma * z - sigma ** 2 / 2)
    e2 = rng.standard_normal(n) * math.sqrt(1 - 0.95 ** 2)
    z2 = np.empty(n)
    z2[0] = e2[0]
    for i in range(1, n):
        z2[i] = 0.95 * z2[i - 1] + e2[i]
    ws = np.clip(2.0 + 4.2 * hs ** 0.8 + 1.6 * z2, 0, None)
    return hs, ws


def load_csv_hindcast(path: str):
    """CSV with header `time,hs,ws` (hourly, starting 1 Jan). Feb-29 rows are dropped."""
    hs, ws = [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("time", "")[5:10] == "02-29":
                continue
            hs.append(float(row["hs"]))
            ws.append(float(row["ws"]))
    return np.array(hs), np.array(ws)


# --------------------------------------------------------------------------
# External (third-party) engine adapter
# --------------------------------------------------------------------------

class ExternalEngine:
    """Calls a third-party downtime tool over HTTP.

    Configure with env vars:
        TNI_EXTERNAL_URL   endpoint that runs a simulation
        TNI_EXTERNAL_TOKEN bearer token (optional)

    The payload/response mapping below is a template - adapt it to the tool's API.
    """
    name = "external"

    def __init__(self, site_lat: float, site_lon: float, port_lat: float = None, port_lon: float = None):
        self.url = os.environ.get("TNI_EXTERNAL_URL")
        self.token = os.environ.get("TNI_EXTERNAL_TOKEN")
        self.site = (site_lat, site_lon)
        if not self.url:
            raise RuntimeError("TNI_EXTERNAL_URL is not set - cannot use the external weather engine")

    def _to_payload(self, steps, start: date, years: int) -> dict:
        return {
            "site": {"lat": self.site[0], "lon": self.site[1]},
            "start_date": start.isoformat(),
            "years": years,
            "activities": [
                {"name": s.name, "duration_h": s.duration_h, "location": s.where,
                 "limits": {"hs_max": s.hs_max, "ws_max": s.ws_max}}
                for s in steps
            ],
        }

    def _from_response(self, data: dict) -> np.ndarray:
        # Expect either per-year durations or percentiles.
        if "durations_h" in data:
            return np.array(data["durations_h"], dtype=float)
        return np.array([data["p10_h"], data["p50_h"], data["p90_h"]], dtype=float)

    def simulate(self, steps, start: date, years: int) -> np.ndarray:
        import httpx
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        r = httpx.post(self.url, json=self._to_payload(steps, start, years), headers=headers, timeout=300)
        r.raise_for_status()
        return self._from_response(r.json())


_engine_cache: dict[tuple, HindcastEngine] = {}


def get_engine(key: str, lat: float, lon: float, years: int) -> DowntimeEngine:
    if key == "external":
        return ExternalEngine(lat, lon)
    ck = (key, round(lat, 3), round(lon, 3), years)
    if ck not in _engine_cache:
        if key == "synthetic":
            hs, ws = synthetic_hindcast(lat, lon, years)
            _engine_cache[ck] = HindcastEngine(hs, ws, name=f"synthetic hindcast ({years} y)")
        elif key.startswith("csv:"):
            path = key[4:]
            hs, ws = load_csv_hindcast(path)
            _engine_cache[ck] = HindcastEngine(hs, ws, name=f"hindcast {os.path.basename(path)}")
        else:
            raise ValueError(f"Unknown weather provider '{key}'")
    return _engine_cache[ck]
