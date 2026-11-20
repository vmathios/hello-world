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
