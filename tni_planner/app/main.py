"""FastAPI app: REST API + static web UI."""
from __future__ import annotations

import json
import pathlib
import shutil

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .engine import run_project
from .models import Project, ProjectResult

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

app = FastAPI(title="T&I Concept Planner", version="0.1.0")


@app.get("/api/sample", response_model=Project)
def sample() -> Project:
    return Project.model_validate_json((DATA / "sample_project.json").read_text())


@app.post("/api/run", response_model=ProjectResult)
def run(project: Project) -> ProjectResult:
    try:
        return run_project(project)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/api/hindcast")
async def upload_hindcast(file: UploadFile) -> dict:
    """Upload a `time,hs,ws` hourly CSV; returns the provider key to put in `weather`."""
    name = pathlib.Path(file.filename or "hindcast.csv").name
    if not name.endswith(".csv"):
        raise HTTPException(400, "CSV required")
    dest = DATA / "hindcasts" / name
    dest.parent.mkdir(exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"weather": f"csv:{dest}"}


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


# ---- ABPmer integration ----

from fastapi import Body
from fastapi.responses import Response

from . import abpmer
from .engine import build_sequence, distance_nm

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.post("/api/abpmer/export")
def abpmer_export(project: Project = Body(...), concept: str = Body(...), package: str = Body(...),
                  mode: str = Body("auto")):
    """ABPmer input workbook for one work package.

    mode: "full" = every trip listed, repeat 1; "cycle" = one trip, repeat = number of trips;
    "auto" = cycle when quantity divides evenly into trips, else full.
    """
    c = next((c for c in project.concepts if c.name == concept), None)
    pkg = c and next((p for p in c.packages if p.id == package), None)
    if not pkg:
        raise HTTPException(404, f"Package '{package}' not found in concept '{concept}'")
    v = next((v for v in c.vessels if v.name == pkg.vessel), None)
    port = next((p for p in c.ports if p.name == pkg.port), None)
    if not v or not port:
        raise HTTPException(422, "Package references unknown vessel or port")
    nm = distance_nm(port.location, project.site)
    cap = max(1, v.deck_capacity)
    cycle = mode == "cycle" or (mode == "auto" and pkg.quantity % cap == 0)
    steps, trips = build_sequence(pkg, v, nm, port.location, project.site, trips_limit=1 if cycle else None)
    sl = pkg.survival_limit
    data = abpmer.export_input(f"{pkg.name} - {c.name}", steps, repeat=trips if cycle else 1,
                               survival=(sl.hs_max, sl.window_h) if sl else (3.5, 24.0))
    fname = f"ABPmer_input_{c.name}_{pkg.id}".replace(" ", "_")
    fname = "".join(ch for ch in fname if ch.isalnum() or ch in "_-+") + ".xlsx"
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/api/abpmer/import")
async def abpmer_import(file: UploadFile) -> dict:
    """Upload an ABPmer RESULT workbook; returns an id to set as `abpmer_result` on a package."""
    try:
        table = abpmer.parse_result(await file.read())
    except Exception as e:  # noqa: BLE001 - report any parse problem to the user
        raise HTTPException(422, f"Could not read ABPmer result: {e}")
    rid = abpmer.save_result(table)
    return {"id": rid, **abpmer.summary(table)}
