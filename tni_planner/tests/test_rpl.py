import pytest
from fastapi.testclient import TestClient
from pyproj import Transformer

from app import rpl
from app.engine import build_sequence
from app.main import app
from app.models import Coord, Step, Vessel, WeatherLimits, WorkPackage

CSV_LL = """Cable_ID,From,To,Latitude,Longitude
C1,OSS,W1,54.00,6.00
C1,OSS,W1,54.00,6.01
C1,OSS,W1,54.01,6.01
C2,W1,W2,54.01,6.01
C2,W1,W2,54.02,6.01
"""


def test_parse_latlon_lengths_and_order():
    cables = rpl.parse_rpl(CSV_LL)
    assert [c["id"] for c in cables] == ["C1", "C2"]
    c1 = cables[0]
    assert c1["from"] == "OSS" and c1["to"] == "W1" and c1["start"] == [54.0, 6.0] and c1["end"] == [54.01, 6.01]
    assert c1["length_m"] == pytest.approx(654 + 1112, rel=0.01)


def test_parse_easting_northing_needs_epsg():
    t = Transformer.from_crs(4326, 32631, always_xy=True)
    lines = ["cable_id,easting,northing,kp"]
    for lat, lon, kp in [(54.0, 3.0, 0.0), (54.0, 3.02, 1.31)]:
        e, n = t.transform(lon, lat)
        lines.append(f"X,{e:.2f},{n:.2f},{kp}")
    text = "\n".join(lines)
    with pytest.raises(ValueError, match="EPSG_REQUIRED"):
        rpl.parse_rpl(text)
    c = rpl.parse_rpl(text, epsg=32631)[0]
    assert c["start"] == pytest.approx([54.0, 3.0], abs=1e-6)
    assert c["length_m"] == pytest.approx(1310)          # KP takes precedence


def test_sequence_uses_cable_positions_and_rate():
    cables = rpl.parse_rpl(CSV_LL)
    pkg = WorkPackage(id="IAC", name="IAC", component="cable", quantity=99, vessel="V", port="P",
                      install_steps=[Step(name="pull-in", duration_h=2),
                                     Step(name="freelay", duration_h=1, rate_m_per_h=500),
                                     Step(name="2nd end", duration_h=3, position="end")],
                      infield_speed_kn=6)
    v = Vessel(name="V", day_rate_eur=1, deck_capacity=10, transit_speed_kn=10)
    steps, trips = build_sequence(pkg, v, Coord(lat=53.5, lon=6.0), Coord(lat=54, lon=6), cables)
    assert trips == 1
    lay = next(s for s in steps if "C1 freelay" in s.name)
    assert lay.duration_h == pytest.approx(cables[0]["length_m"] / 500)
    assert lay.window_h == pytest.approx(lay.duration_h * 1.5)
    end2 = next(s for s in steps if "C1 2nd end" in s.name)
    assert (end2.lat, end2.lon) == (54.01, 6.01)
    assert not any("move to C2" in s.name for s in steps if s.duration_h > 0.01)   # C2 starts where C1 ends


def test_api_rpl_upload_and_run(tmp_path, monkeypatch):
    monkeypatch.setattr(rpl, "RPL_DIR", tmp_path)
    c = TestClient(app)
    r = c.post("/api/rpl", files={"file": ("my_rpl.csv", CSV_LL, "text/csv")})
    assert r.status_code == 200 and r.json()["cables"] == 2
    proj = c.get("/api/sample").json()
    proj["concepts"][0]["packages"][1]["rpl"] = r.json()["id"]
    res = c.post("/api/run", json=proj).json()
    iac = res["concepts"][0]["packages"][1]
    assert iac["quantity"] == 2 and iac["route_km"] == pytest.approx(2.88, abs=0.05)
    assert iac["cost_eur"] == pytest.approx(iac["day_rate_eur"] * iac["p50_days"], rel=0.03)
