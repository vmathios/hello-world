import io
import json
import pathlib
from datetime import date, datetime, timedelta

import numpy as np
import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import abpmer
from app.main import app
from app.weather import HindcastEngine, SeqStep, HOURS_PER_YEAR, merge_groups

EXAMPLE = pathlib.Path(__file__).resolve().parent.parent / "data" / "abpmer_examples" / "result_iac_lay.xlsx"


def fake_result(net_days=10.0, operation="Dummy op") -> bytes:
    """Minimal workbook with the ABPmer RESULT 'Whole Operation' layout."""
    wb = openpyxl.Workbook()
    tl = wb.active; tl.title = "Task List"
    tl["A2"], tl["B2"] = "Operation Name:", operation
    ws = wb.create_sheet("Whole Operation")
    ws["A2"] = "Whole Operation Net Duration (Hours)"; ws["A3"] = net_days * 24
    ws["A4"] = "Whole Operation Net Duration (Days)"; ws["A5"] = net_days
    ws.cell(4, 4, "Weather Down Time for the Whole Operation (Days)")
    ws.cell(4, 57, "Extended Total Duration of the Whole Operation (Days)")
    ws["A10"] = "Probability of Non-Exceedance"
    starts = [datetime(2001, 1, 4) + timedelta(weeks=k) for k in range(52)]
    for k, d in enumerate(starts):
        ws.cell(10, 3 + k, d); ws.cell(10, 56 + k, d)
    for i in range(101):
        p = i / 100
        ws.cell(11 + i, 1, p)
        for k in range(52):
            wdt = (5 + 10 * p) * (2 if k < 13 else 1)        # Q1 starts are twice as bad
            ws.cell(11 + i, 3 + k, wdt); ws.cell(11 + i, 56 + k, wdt + net_days)
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


def test_parse_fake_result():
    t = abpmer.parse_result(fake_result())
    assert t["operation"] == "Dummy op" and t["net_days"] == 10.0
    assert len(t["probs"]) == 101 and len(t["start_doy"]) == 52
    assert abpmer.lookup_hours(t, date(2028, 7, 1), 50) == pytest.approx((10 + 10) * 24)
    assert abpmer.lookup_hours(t, date(2028, 1, 4), 50) == pytest.approx((10 + 20) * 24)
    assert abpmer.lookup_hours(t, date(2028, 7, 1), 90) > abpmer.lookup_hours(t, date(2028, 7, 1), 10)


@pytest.mark.skipif(not EXAMPLE.exists(), reason="private ABPmer example not present")
def test_parse_real_example():
    t = abpmer.parse_result(EXAMPLE.read_bytes())
    assert t["operation"] == "IAC Lay"
    k = t["probs"].index(0.5)
    assert t["total_days"][k][0] == pytest.approx(t["wdt_days"][k][0] + t["net_days"], abs=0.01)


def test_export_layout():
    steps = [SeqStep("Pull-in", 2, 2.0, 15, "site", 3, 0.75, True, False, 54.0, 6.0),
             SeqStep("Freelay", 8, 2.5, 15, "site", 12, None, False, False, 54.0, 6.0)]
    wb = openpyxl.load_workbook(io.BytesIO(abpmer.export_input("IAC", steps, repeat=5)))
    ws = wb.active
    assert ws["B2"].value == "IAC" and ws["H4"].value == 5
    assert ws["A13"].value == "Survival Limit" and ws["G13"].value == 3.5 and ws["F13"].value == 24
    row = [c.value for c in ws[14]][:14]
    assert row[:7] == ["Pull-in", 6.0, 54.0, None, 2, 3, 2.0]
    assert row[9:14] == [15, 10, 600, 0.75, 1]


def test_window_and_grouping():
    hs = np.full(HOURS_PER_YEAR, 0.5)
    hs[4] = 3.0                                   # storm at hour 4: hours 0-3 are a 4h window
    eng = HindcastEngine(hs, np.zeros_like(hs))
    # 3h task needing a 6h window (duration x 2) cannot use 0-3 -> starts at 5, ends 8
    assert eng.run_once([SeqStep("x", 3, 2.0, None, window_h=6)], 0) == 8.0
    a = SeqStep("a", 2, 2.0, None, window_h=2, group_with_next=True)
    b = SeqStep("b", 3, 2.0, None, window_h=3)
    assert len(merge_groups([a, b])) == 1
    # grouped: one 5h window needed -> 0-3 too short -> 5..10
    assert eng.run_once([a, b], 0) == 10.0
    # ungrouped: a at 0-2, b needs 3h from 2 (only 2-3 free) -> waits to 5 -> ends 8
    a2 = SeqStep("a", 2, 2.0, None, window_h=2)
    assert eng.run_once([a2, b], 0) == 8.0


def test_api_export_and_import_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(abpmer, "RESULTS_DIR", tmp_path)
    c = TestClient(app)
    proj = c.get("/api/sample").json()
    r = c.post("/api/abpmer/export", json={"project": proj, "concept": proj["concepts"][0]["name"], "package": "IAC"})
    assert r.status_code == 200
    ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
    assert ws["H4"].value == 5                       # 60 cables / 12 per trip -> one cycle x 5
    r = c.post("/api/abpmer/import", files={"file": ("res.xlsx", fake_result(80.0, "IAC"), "application/octet-stream")})
    assert r.status_code == 200
    rid = r.json()["id"]
    proj["concepts"][0]["packages"][1]["abpmer_result"] = rid
    res = c.post("/api/run", json=proj).json()
    iac = res["concepts"][0]["packages"][1]
    assert iac["downtime_source"] == "ABPmer: IAC"
    assert iac["p50_days"] == pytest.approx(90.0, abs=0.2)   # Q2 start: 80 net + 10 WDT
