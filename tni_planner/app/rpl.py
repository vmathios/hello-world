"""Route Position List (RPL) import for cable packages.

CSV, one row per route point, in installation order. Column names are case-insensitive:

    cable_id                  (aliases: cable, route, id)            required
    lat, lon                  (latitude/longitude, WGS84)             or
    easting, northing         (+ EPSG code at upload, e.g. 32631)
    kp                        optional, km along route - used for length if present
    from, to                  optional, asset names (e.g. WTG-01, OSS)

Points of a cable are taken in file order. Cables are installed in order of first appearance.
"""
from __future__ import annotations

import csv
import io
import json
import math
import pathlib
import re
import uuid
from typing import Optional

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
RPL_DIR = DATA / "rpl"
SAMPLES_DIR = DATA / "samples"

ALIASES = {
    "cable_id": ("cable_id", "cable", "cableid", "route", "route_id", "id"),
    "lat": ("lat", "latitude"),
    "lon": ("lon", "long", "lng", "longitude"),
    "easting": ("easting", "east", "x", "e"),
    "northing": ("northing", "north", "y", "n"),
    "kp": ("kp", "kp_km"),
    "from": ("from", "from_asset", "start_asset"),
    "to": ("to", "to_asset", "end_asset"),
}


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _columns(header: list[str]) -> dict[str, str]:
    norm = {h.strip().lower().replace(" ", "_"): h for h in header}
    out = {}
    for key, names in ALIASES.items():
        for n in names:
            if n in norm:
                out[key] = norm[n]
                break
    return out


def parse_rpl(text: str, epsg: Optional[int] = None) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    cols = _columns(reader.fieldnames or [])
    if "cable_id" not in cols:
        raise ValueError("RPL needs a 'cable_id' column")
    use_ll = "lat" in cols and "lon" in cols
    use_en = "easting" in cols and "northing" in cols
    if not use_ll and not use_en:
        raise ValueError("RPL needs lat/lon or easting/northing columns")
    transform = None
    if not use_ll:
        if not epsg:
            raise ValueError("EPSG_REQUIRED: easting/northing given - provide the EPSG code (e.g. 32631 for UTM 31N)")
        from pyproj import Transformer
        transform = Transformer.from_crs(int(epsg), 4326, always_xy=True).transform

    cables: dict[str, dict] = {}
    for i, row in enumerate(reader, start=2):
        cid = (row.get(cols["cable_id"]) or "").strip()
        if not cid:
            continue
        try:
            if use_ll:
                lat, lon = float(row[cols["lat"]]), float(row[cols["lon"]])
            else:
                lon, lat = transform(float(row[cols["easting"]]), float(row[cols["northing"]]))
        except (TypeError, ValueError):
            raise ValueError(f"RPL line {i}: invalid coordinates")
        c = cables.setdefault(cid, {"id": cid, "from": None, "to": None, "points": [], "kp": []})
        c["points"].append((round(lat, 6), round(lon, 6)))
        if "kp" in cols and row.get(cols["kp"]) not in (None, ""):
            c["kp"].append(float(row[cols["kp"]]))
        if "from" in cols and row.get(cols["from"]) and not c["from"]:
            c["from"] = row[cols["from"]].strip()
        if "to" in cols and row.get(cols["to"]):
            c["to"] = row[cols["to"]].strip()

    out = []
    for c in cables.values():
        pts = c["points"]
        if len(pts) < 2:
            raise ValueError(f"Cable '{c['id']}' has fewer than 2 route points")
        if len(c["kp"]) >= 2:
            length = (max(c["kp"]) - min(c["kp"])) * 1000
        else:
            length = sum(haversine_m(*pts[k], *pts[k + 1]) for k in range(len(pts) - 1))
        out.append({"id": c["id"], "from": c["from"], "to": c["to"],
                    "start": list(pts[0]), "end": list(pts[-1]), "length_m": round(length, 1),
                    "n_points": len(pts)})
    if not out:
        raise ValueError("RPL contains no cables")
    return out


def save_rpl(name: str, cables: list[dict]) -> str:
    RPL_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "rpl"
    rid = f"{slug}-{uuid.uuid4().hex[:6]}"
    (RPL_DIR / f"{rid}.json").write_text(json.dumps({"name": name, "cables": cables}))
    return rid


def load_rpl(rid: str) -> list[dict]:
    if not re.fullmatch(r"[a-z0-9-]+", rid or ""):
        raise ValueError(f"Invalid RPL id '{rid}'")
    p = RPL_DIR / f"{rid}.json"
    if p.exists():
        return json.loads(p.read_text())["cables"]
    s = SAMPLES_DIR / f"{rid}.csv"
    if s.exists():
        return parse_rpl(s.read_text())
    raise ValueError(f"RPL '{rid}' not found - upload it first")


def summary(cables: list[dict]) -> dict:
    return {"cables": len(cables), "total_km": round(sum(c["length_m"] for c in cables) / 1000, 1),
            "min_km": round(min(c["length_m"] for c in cables) / 1000, 2),
            "max_km": round(max(c["length_m"] for c in cables) / 1000, 2)}
