"""ABPmer weather-downtime tool integration (Excel in / Excel out).

* `export_input`  - writes the ABPmer task-list input workbook for one work package
                    (layout of the ABPmer template: headers rows 2-12, tasks from row 13).
* `parse_result`  - reads the 'Whole Operation' sheet of an ABPmer RESULT workbook:
                    total duration (net + WDT) per probability of non-exceedance
                    (P0..P100) for 52 weekly start dates.
* `lookup_hours`  - Pxx duration for a given start date (interpolated between weeks).
"""
from __future__ import annotations

import io
import json
import pathlib
import re
import uuid
import warnings
from datetime import date, datetime

import numpy as np
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .weather import SeqStep

# ABPmer workbooks carry conditional formats openpyxl cannot read; harmless.
warnings.filterwarnings("ignore", message="Failed to load a conditional formatting rule")

RESULTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "abpmer_results"
FIRST_TASK_ROW = 13

WIND_REF_HEIGHT_M = 10
WIND_AVG_PERIOD_S = 600

HEADERS_ROW10 = {1: "Tasks", 2: "Location", 5: "Durations", 7: "Thresholds (not to be exceeded whilst working)",
                 14: "Other working criteria", 18: "Additional Outputs", 19: "Inputs for Currents",
                 24: "Free Space for Notes and Working"}
HEADERS_ROW11 = ["Task name", "Location of task", None, None, "Task duration", "Weather window", "Wave height",
                 "Wave period", "Wave period exception", "Wind speed", "Wind ref. height", "Wind avg. period",
                 "Current speed", "Group with following task", "Daylight only", "Not on falling tide",
                 "Not on rising tide", "Task group ID", "WL Range 1", "Peak CurrSpd 1",
                 "Time Peak CurrSpd after HW", "(WL Range 2)", "(Peak CurrSpd 2)"]
HEADERS_ROW12 = ["Column1", "Longitude", "Latitude", "Client data name", "(hrs)", "(hrs)2", "(m)", "(s)",
                 "Allow work above (s)", "(m/s)", "(m)3", "(s)4", "(m/s)", "(flag=1)", "(flag=1)", "(flag=1)",
                 "(flag=1)", "(for additional information if required)", "(m)", "(m/s)", "(hrs)", "(m)", "(m/s)"]


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

def export_input(operation: str, steps: list[SeqStep], repeat: int = 1,
                 survival: tuple[float, float] | None = (3.5, 24.0), sheet: str = "Task list") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet[:31]
    bold = Font(bold=True)
    ws["A2"], ws["B2"] = "Operation Name:", operation
    ws["A3"], ws["B3"] = "Version:", "1"
    ws["G4"], ws["H4"], ws["I4"] = "Get results for repeating this task list", repeat, "times."
    ws["A5"] = "Net cycle time (excluding weather down time)"
    ws["A6"], ws["B6"] = f"=SUM(E{FIRST_TASK_ROW}:E9999)", "hrs"
    ws["A7"], ws["B7"] = "=A6/24", "days"
    for c, v in HEADERS_ROW10.items():
        ws.cell(10, c, v).font = bold
    for i, v in enumerate(HEADERS_ROW11, start=1):
        if v:
            ws.cell(11, i, v).font = bold
    for i, v in enumerate(HEADERS_ROW12, start=1):
        ws.cell(12, i, v).font = bold
    for c in ("A2", "A3", "A5", "H4"):
        ws[c].font = bold
    ws["H4"].fill = PatternFill("solid", fgColor="FFF2CC")

    r = FIRST_TASK_ROW
    if survival:
        ws.cell(r, 1, "Survival Limit"); ws.cell(r, 5, 0); ws.cell(r, 6, survival[1]); ws.cell(r, 7, survival[0])
        r += 1
    for s in steps:
        weather = s.hs_max is not None or s.ws_max is not None or s.uc_max is not None
        row = {1: s.name, 2: s.lon, 3: s.lat, 5: round(s.duration_h, 3),
               6: round(s.window_h if s.window_h is not None else s.duration_h, 3),
               7: s.hs_max, 10: s.ws_max, 13: s.uc_max,
               14: 1 if s.group_with_next else None, 15: 1 if s.daylight_only else None}
        if s.ws_max is not None or weather:
            row[11], row[12] = WIND_REF_HEIGHT_M, WIND_AVG_PERIOD_S
        for c, v in row.items():
            if v is not None:
                ws.cell(r, c, v)
        r += 1

    widths = {1: 48, 2: 11, 3: 11, 4: 16}
    for c in range(1, 25):
        ws.column_dimensions[get_column_letter(c)].width = widths.get(c, 12)
    for row in ws.iter_rows(min_row=10, max_row=12):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = f"B{FIRST_TASK_ROW}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------

def _runs(row: tuple, pred) -> list[list[int]]:
    """Contiguous column-index runs where pred(value) holds."""
    runs, cur = [], []
    for j, v in enumerate(row):
        if pred(v):
            cur.append(j)
        elif cur:
            runs.append(cur); cur = []
    if cur:
        runs.append(cur)
    return runs


def parse_result(data: bytes) -> dict:
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    if "Whole Operation" not in wb.sheetnames:
        raise ValueError("Not an ABPmer result workbook: sheet 'Whole Operation' not found")
    operation = "ABPmer result"
    if "Task List" in wb.sheetnames:
        for row in wb["Task List"].iter_rows(min_row=1, max_row=4, max_col=2, values_only=True):
            if row[0] == "Operation Name:" and row[1]:
                operation = str(row[1])
    rows = [tuple(r) for r in wb["Whole Operation"].iter_rows(values_only=True)]

    net_days = None
    for i, r in enumerate(rows[:10]):
        if r and isinstance(r[0], str) and "Net Duration (Days)" in r[0]:
            net_days = float(rows[i + 1][0])
    hdr = next((i for i, r in enumerate(rows) if r and isinstance(r[0], str)
                and r[0].startswith("Probability of Non-Exceedance")), None)
    if hdr is None or net_days is None:
        raise ValueError("Could not find net duration / probability table in 'Whole Operation'")

    is_date = lambda v: isinstance(v, (datetime, date))
    blocks = _runs(rows[hdr], is_date)
    if not blocks:
        raise ValueError("No weekly start dates found in 'Whole Operation'")
    # Blocks are [weather downtime only, extended total]; label row 4 tells which is which.
    labels = rows[3] if len(rows) > 3 else ()
    def label_for(block):
        for j in range(block[0], block[-1] + 1):
            if 0 <= j < len(labels) and isinstance(labels[j], str):
                return labels[j]
        return ""
    total_block = next((b for b in blocks if "Total" in label_for(b)), blocks[-1])
    wdt_block = next((b for b in blocks if "Down Time" in label_for(b)), None)

    probs, total, wdt = [], [], []
    for r in rows[hdr + 1:]:
        if not r or r[0] is None:
            break
        try:
            p = float(r[0])
        except (TypeError, ValueError):
            break
        probs.append(p)
        total.append([float(r[j]) for j in total_block])
        if wdt_block:
            wdt.append([float(r[j]) for j in wdt_block])
    starts = [rows[hdr][j] for j in total_block]
    return {
        "operation": operation,
        "net_days": net_days,
        "start_doy": [d.timetuple().tm_yday - 1 for d in starts],
        "start_labels": [d.strftime("%d %b") for d in starts],
        "probs": probs,
        "total_days": total,
        "wdt_days": wdt,
    }


def save_result(table: dict) -> str:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", table["operation"].lower()).strip("-")[:30] or "result"
    rid = f"{slug}-{uuid.uuid4().hex[:6]}"
    (RESULTS_DIR / f"{rid}.json").write_text(json.dumps(table))
    return rid


def load_result(rid: str) -> dict:
    if not re.fullmatch(r"[a-z0-9-]+", rid or ""):
        raise ValueError(f"Invalid ABPmer result id '{rid}'")
    path = RESULTS_DIR / f"{rid}.json"
    if not path.exists():
        raise ValueError(f"ABPmer result '{rid}' not found - import it first")
    return json.loads(path.read_text())


def lookup_hours(table: dict, start: date, percentile: float) -> float:
    """Total duration [h] at the given percentile for an operation starting on `start`."""
    probs = np.array(table["probs"])
    k = int(np.argmin(np.abs(probs - percentile / 100)))
    vals = np.array(table["total_days"][k])
    doy = np.array(table["start_doy"], dtype=float)
    d = start.timetuple().tm_yday - 1
    # circular interpolation across the year
    xs = np.concatenate([doy - 365, doy, doy + 365])
    ys = np.concatenate([vals, vals, vals])
    return float(np.interp(d, xs, ys)) * 24


def summary(table: dict, percentile: float = 50) -> dict:
    probs = np.array(table["probs"])
    k = int(np.argmin(np.abs(probs - percentile / 100)))
    return {"operation": table["operation"], "net_days": round(table["net_days"], 1),
            "by_week": [{"start": l, "total_days": round(v, 1)}
                        for l, v in zip(table["start_labels"], table["total_days"][k])]}
