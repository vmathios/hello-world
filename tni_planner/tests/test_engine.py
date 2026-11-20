import json
import pathlib
from datetime import date

import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.weather import HindcastEngine, SeqStep, HOURS_PER_YEAR

SAMPLE = pathlib.Path(__file__).resolve().parent.parent / "data" / "sample_project.json"


def test_calm_weather_has_no_downtime():
    hs = np.full(HOURS_PER_YEAR * 2, 0.5)
    eng = HindcastEngine(hs, hs.copy())
    out = eng.simulate([SeqStep("a", 10, 1.0, 10), SeqStep("b", 5.5)], date(2028, 5, 1), 2)
    assert list(out) == [16.0, 16.0]


def test_waits_for_continuous_window():
    hs = np.full(HOURS_PER_YEAR, 0.5)
    hs[3:8] = 3.0                       # storm hours 3-7
    hs[12] = 3.0                        # short break: 8-11 is only a 4h window
    eng = HindcastEngine(hs, np.zeros_like(hs))
    # 6h job starting t=0 cannot fit in 0-2 or 8-11, so starts at 13 -> elapsed 19h
    assert eng.run_once([SeqStep("x", 6, 2.0, None)], 0) == 19.0


def test_impossible_limits_are_infinite():
    hs = np.full(HOURS_PER_YEAR, 3.0)
    eng = HindcastEngine(hs, np.zeros_like(hs))
    assert np.isinf(eng.run_once([SeqStep("x", 2, 1.0, None)], 0))


def test_api_runs_sample():
    c = TestClient(app)
    proj = c.get("/api/sample").json()
    r = c.post("/api/run", json=proj)
    assert r.status_code == 200
    res = r.json()
    assert len(res["concepts"]) == 3
    for con in res["concepts"]:
        for p in con["packages"]:
            assert p["p10_days"] <= p["p50_days"] <= p["p90_days"]
            assert p["p50_days"] >= p["net_duration_days"]
        wtg = next(p for p in con["packages"] if p["id"] == "WTG")
        mp = next(p for p in con["packages"] if p["id"] == "MP")
        assert wtg["start"] == mp["p50_end"]   # dependency chaining


def test_bad_reference_is_422():
    proj = json.loads(SAMPLE.read_text())
    proj["concepts"][0]["packages"][0]["vessel"] = "nope"
    r = TestClient(app).post("/api/run", json=proj)
    assert r.status_code == 422 and "unknown vessel" in r.json()["detail"]
