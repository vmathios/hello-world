"""Domain model for transport & installation (T&I) concepts."""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class Coord(BaseModel):
    lat: float
    lon: float


class WeatherLimits(BaseModel):
    """Operational limits. None = not weather sensitive for that parameter."""
    hs_max: Optional[float] = Field(None, description="Significant wave height limit [m]")
    ws_max: Optional[float] = Field(None, description="Wind speed limit [m/s] (at reference height)")


class Step(BaseModel):
    """One non-splittable activity: needs a continuous weather window of `duration_h`."""
    name: str
    duration_h: float
    limits: WeatherLimits = WeatherLimits()


class Port(BaseModel):
    name: str
    location: Coord
    day_rate_eur: float = 0.0          # quayside / laydown rental
    fixed_cost_eur: float = 0.0        # e.g. port upgrades, quay reinforcement


class Vessel(BaseModel):
    name: str
    type: str = ""                     # e.g. "Jack-up WTIV", "HLV", "CLV"
    transit_speed_kn: float = 10.0
    day_rate_eur: float
    mob_demob_eur: float = 0.0
    deck_capacity: int = Field(1, description="Units carried per trip")


class WorkPackage(BaseModel):
    """A campaign: one vessel installs `quantity` units shuttling from one port."""
    id: str
    name: str                          # e.g. "Monopile installation"
    component: str                     # e.g. "monopile", "WTG", "array cable"
    quantity: int
    vessel: str                        # Vessel.name
    port: str                          # Port.name
    start_date: Optional[date] = None  # fixed earliest start
    after: Optional[str] = None        # WorkPackage.id this follows (P50 finish)
    lag_days: float = 0.0              # lag after predecessor finish
    load_steps: list[Step] = []        # per unit, at port
    transit_limits: WeatherLimits = WeatherLimits()
    install_steps: list[Step] = []     # per unit, at site
    infield_move_h: float = 2.0        # between installation positions
    extra_costs_eur: float = 0.0


class Concept(BaseModel):
    name: str
    description: str = ""
    ports: list[Port]
    vessels: list[Vessel]
    packages: list[WorkPackage]


class Project(BaseModel):
    name: str
    site: Coord
    n_turbines: int = 0
    n_foundations: int = 0
    n_cables: int = 0
    concepts: list[Concept]
    weather: str = Field("synthetic", description="Weather provider key")
    hindcast_years: int = 20
    percentile: float = 50.0


# ---- results ----

class TripResult(BaseModel):
    start: str
    end: str


class PackageResult(BaseModel):
    id: str
    name: str
    component: str
    vessel: str
    port: str
    quantity: int
    trips: int
    transit_nm: float
    net_duration_days: float           # no weather
    start: str
    p50_end: str
    p10_days: float
    p50_days: float
    p90_days: float
    weather_downtime_pct: float
    cost_eur: dict[str, float]


class ConceptResult(BaseModel):
    name: str
    description: str
    start: str
    p50_end: str
    p50_total_days: float
    total_cost_eur: float
    cost_breakdown_eur: dict[str, float]
    packages: list[PackageResult]


class ProjectResult(BaseModel):
    project: str
    weather_provider: str
    percentile: float
    concepts: list[ConceptResult]
