"""Builds docs/architecture.svg/.html (workflow + data model)."""
import html, pathlib, sys

W = 1640
INK, INK2, MUTED, LINE, SURF, BG = "#0b0b0b", "#52514e", "#6f6e69", "#c9c8c0", "#fcfcfb", "#f4f3ef"
ACC = {"in": "#2a78d6", "proc": "#52514e", "wx": "#1baf7a", "out": "#eb6834", "fut": "#9a998f", "store": "#6250d6"}
out = []
e = html.escape

def box(x, y, w, title, lines=(), kind="proc", dashed=False, mono=False, hdr=None):
    lh = 17
    h = 34 + lh * len(lines) + (8 if lines else 0)
    c = ACC[kind]
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{SURF}" stroke="{LINE if not dashed else c}" '
               f'stroke-width="1.5" {"stroke-dasharray=\'6 4\'" if dashed else ""}/>')
    out.append(f'<rect x="{x}" y="{y}" width="5" height="{h}" rx="2" fill="{c}"/>')
    if hdr:
        out.append(f'<text x="{x + w - 12}" y="{y + 22}" text-anchor="end" font-size="11" fill="{MUTED}">{e(hdr)}</text>')
    out.append(f'<text x="{x + 16}" y="{y + 23}" font-size="14" font-weight="600" fill="{INK}">{e(title)}</text>')
    fam = "ui-monospace, Menlo, Consolas, monospace" if mono else "inherit"
    for i, l in enumerate(lines):
        col = MUTED if l.startswith("·") is False and l.startswith("  ") else INK2
        out.append(f'<text x="{x + 16}" y="{y + 46 + i * lh}" font-size="12" fill="{col}" font-family="{fam}">{e(l)}</text>')
    return (x, y, w, h)

def arrow(x1, y1, x2, y2, label=None, dashed=False, curve=None, via=None):
    d = f"M{x1},{y1} L{x2},{y2}" if not curve else f"M{x1},{y1} C{curve} {x2},{y2}"
    if via:
        d = f"M{x1},{y1} " + " ".join(f"L{a},{b}" for a, b in via) + f" L{x2},{y2}"
    out.append(f'<path d="{d}" fill="none" stroke="{INK2}" stroke-width="1.5" marker-end="url(#a)" '
               f'{"stroke-dasharray=\'5 4\'" if dashed else ""}/>')
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 6
        out.append(f'<text x="{mx}" y="{my}" text-anchor="middle" font-size="11" fill="{MUTED}">{e(label)}</text>')

R = lambda b: (b[0] + b[2], b[1] + b[3] / 2)
L = lambda b: (b[0], b[1] + b[3] / 2)
B = lambda b: (b[0] + b[2] / 2, b[1] + b[3])
T = lambda b: (b[0] + b[2] / 2, b[1])

def section(y, n, title, sub):
    out.append(f'<text x="40" y="{y}" font-size="20" font-weight="700" fill="{INK}">{n}  {e(title)}</text>')
    out.append(f'<text x="40" y="{y + 22}" font-size="13" fill="{INK2}">{e(sub)}</text>')

# ---------------- Title ----------------
out.append(f'<text x="40" y="52" font-size="26" font-weight="700" fill="{INK}">T&amp;I Concept Planner — workflow &amp; data model (MVP)</text>')
out.append(f'<text x="40" y="78" font-size="13" fill="{INK2}">Status Nov 2026 · branch claude/optimistic-turing-ypnmta · FastAPI backend + web UI</text>')

# legend
x = 960
for k, t in [("in", "Input"), ("proc", "Processing"), ("wx", "Weather downtime"), ("out", "Output"), ("store", "Stored dataset"), ("fut", "Future")]:
    out.append(f'<rect x="{x}" y="62" width="12" height="12" rx="2" fill="{ACC[k]}"/>')
    out.append(f'<text x="{x + 18}" y="72" font-size="12" fill="{INK2}">{t}</text>')
    x += 18 + len(t) * 7 + 22

# ---------------- 1. Workflow ----------------
section(130, "1", "Workflow", "From project-team input to P50 schedule and concept comparison")
y0 = 170
pin = box(40, y0, 270, "Project team input", ["Site coordinates", "No. of WTGs / foundations / cables", "Target start dates"], "in")
con = box(40, y0 + 120, 270, "Concept definition (C1, C2, C3…)", ["Load-out ports (lat/lon)", "Vessels: speed, day rate, deck capacity",
          "Work packages: activity steps,", "  durations, Hs / Uw,10 / Uc limits,", "  contingency, grouping, dependencies"], "in")
rpl = box(40, y0 + 296, 270, "RPL CSV (cable packages)", ["Route points per cable", "lat/lon or Easting/Northing + EPSG", "→ cable ends, route length"], "in")
hc = box(40, y0 + 416, 270, "Hindcast CSV (optional)", ["Hourly time, Hs, Uw,10"], "in")

seq = box(380, y0 + 150, 270, "Sequence builder", ["Trips = cables or units ÷ deck capacity", "Load-out → transit → install per unit",
          "  → infield moves → transit back", "Freelay = route length ÷ lay rate", "Positions per cable from RPL",
          "Weather window = duration × 1.5", "= Pnet activity list (no weather)"], "proc")

sim = box(720, y0, 330, "A · Built-in simulation", ["Persistence analysis over hindcast years", "Each step needs a continuous window",
          "Grouped steps share one window", "→ P10 / P50 / P90 per start date"], "wx")
ab = box(720, y0 + 150, 330, "B · ABPmer (Excel, via e-mail)", ["1  Export input .xlsx (ABPmer template layout)",
         "2  E-mail to ABPmer, receive RESULT .xlsx", "3  Import: 'Whole Operation' sheet", "   = total days per P0…P100 × 52 weekly starts",
         "4  Pxx interpolated to the actual start date"], "wx")
ext = box(720, y0 + 330, 330, "C · External API (stub)", ["HTTP adapter for a future downtime service"], "wx", dashed=True)

sch = box(1110, y0 + 150, 230, "Scheduler", ["Packages in dependency order", "Start = date or predecessor", "  P50 finish + lag",
          "P50 finish = start + P50", "Checks & warnings"], "proc")

g = box(1390, y0, 220, "P50 Gantt chart", ["Per concept & package", "P10–P90 finish whiskers"], "out")
cst = box(1390, y0 + 120, 220, "Vessel CAPEX comparison", ["Day rate × P50 duration", "Split by component"], "out")
tbl = box(1390, y0 + 240, 220, "Detail table / CSV export", ["Net, P10/P50/P90, downtime %", "Route km, CAPEX, source"], "out")
fut = box(1110, y0 + 400, 500, "Future: cost datasets (separate repositories)", ["Fuel, CO2 tax, specialist equipment charter,",
          "service contracts → fed into CAPEX with actual values"], "fut", dashed=True)

arrow(*R(pin), 380, seq[1] + 30, curve=f"345,{pin[1] + pin[3] / 2} 345,{seq[1] + 30}")
arrow(*R(con), *L(seq))
arrow(*R(rpl), 380, seq[1] + seq[3] - 30, curve=f"345,{rpl[1] + rpl[3] / 2} 345,{seq[1] + seq[3] - 30}")
arrow(*R(hc), 720, sim[1] + sim[3] - 15, via=[(700, hc[1] + hc[3] / 2), (700, sim[1] + sim[3] - 15)])
arrow(*R(seq), *L(sim), "steps", curve=f"685,{seq[1] + seq[3] / 2} 685,{sim[1] + sim[3] / 2}")
arrow(*R(seq), *L(ab), "steps")
arrow(*R(seq), *L(ext), dashed=True, curve=f"685,{seq[1] + seq[3] / 2} 685,{ext[1] + ext[3] / 2}")
arrow(*R(sim), sch[0], sch[1] + 25, curve=f"1080,{sim[1] + sim[3] / 2} 1080,{sch[1] + 25}")
arrow(*R(ab), *L(sch))
arrow(*R(ext), sch[0], sch[1] + sch[3] - 20, dashed=True, curve=f"1080,{ext[1] + ext[3] / 2} 1080,{sch[1] + sch[3] - 20}")
for o in (g, cst, tbl):
    arrow(*R(sch), *L(o), curve=f"1365,{sch[1] + sch[3] / 2} 1365,{o[1] + o[3] / 2}")
arrow(*T(fut), cst[0] + cst[2] / 2, cst[1] + cst[3] + 132, dashed=True)

# ---------------- 2. Data model ----------------
y1 = 700
section(y1, "2", "Data model", "Project JSON (input) → stored datasets → results; arrows = 'contains' / 'references'")
y = y1 + 58
prj = box(40, y, 290, "Project", ["name", "site: lat, lon", "n_turbines, n_foundations, n_cables", "weather: synthetic | csv:… | external",
          "hindcast_years, percentile (50)", "concepts: Concept[]"], "in", mono=True)
cpt = box(370, y, 220, "Concept", ["name, description", "ports: Port[]", "vessels: Vessel[]", "packages: WorkPackage[]"], "in", mono=True)
prt = box(630, y, 200, "Port", ["name", "location: lat, lon"], "in", mono=True)
ves = box(630, y + 100, 200, "Vessel", ["name, type", "transit_speed_kn", "day_rate_eur", "deck_capacity"], "in", mono=True)
wp = box(870, y, 350, "WorkPackage", ["id, name, component, quantity", "vessel → Vessel.name", "port → Port.name",
         "start_date | after → WorkPackage.id, lag_days", "load_steps: Step[]  (at port)", "install_steps: Step[] (at site / cable)",
         "transit_limits: WeatherLimits", "infield_move_h, infield_speed_kn", "contingency_factor (1.5)", "survival_limit: Hs 3.5 m / 24 h",
         "rpl → RPL id", "abpmer_result → ABPmer result id"], "in", mono=True)
stp = box(1260, y, 350, "Step", ["name, duration_h", "window_h (default duration × factor)", "rate_m_per_h (e.g. freelay 360 m/h)",
          "position: start | end (cable end)", "group_with_next, daylight_only", "limits: WeatherLimits"], "in", mono=True)
wl = box(1260, y + 170, 350, "WeatherLimits", ["hs_max   Hs  [m]", "ws_max   Uw,10 [m/s] (10 m, 10-min)", "uc_max   Uc  [m/s]"], "in", mono=True)

y2 = y + 300
rp = box(870, y2, 350, "RPL (stored dataset)", ["per cable: id, from, to", "start (lat, lon), end (lat, lon)", "length_m (KP or route geometry)"], "store", mono=True)
abr = box(1260, y2, 350, "ABPmer result (stored dataset)", ["operation, net_days", "probs: P0…P100", "start dates: 52 weekly",
          "total_days[prob][week]  (net + WDT)"], "store", mono=True)

y3 = y2 + 150
pr = box(40, y3, 290, "ProjectResult", ["weather_provider, percentile", "concepts: ConceptResult[]"], "out", mono=True)
cr = box(370, y3, 260, "ConceptResult", ["start, p50_end, p50_total_days", "total_cost_eur", "cost_breakdown_eur by component",
         "packages: PackageResult[]", "warnings[]"], "out", mono=True)
pkr = box(670, y3, 340, "PackageResult", ["quantity, trips, route_km, transit_nm", "net_duration_days (Pnet)", "start, p50_end",
          "p10 / p50 / p90_days, downtime %", "downtime_source: simulation | ABPmer", "day_rate_eur, cost_eur (= rate × P50)"], "out", mono=True)

arrow(*R(prj), *L(cpt))
arrow(cpt[0] + cpt[2], cpt[1] + 40, prt[0], prt[1] + 25)
arrow(cpt[0] + cpt[2], cpt[1] + 60, ves[0], ves[1] + 30)
arrow(cpt[0] + cpt[2] / 2, cpt[1], wp[0] + 60, wp[1], via=[(cpt[0] + cpt[2] / 2, cpt[1] - 12), (wp[0] + 60, cpt[1] - 12)])
arrow(*R(wp), stp[0], stp[1] + 40)
arrow(*B(stp), *T(wl))
arrow(wp[0] + wp[2], wp[1] + 150, wl[0], wl[1] + 25)
arrow(wp[0] + 175, wp[1] + wp[3], *T(rp))
out.append(f'<text x="{wp[0] + 183}" y="{wp[1] + wp[3] + 22}" font-size="11" fill="{MUTED}">rpl</text>')
arrow(wp[0] + wp[2] - 20, wp[1] + wp[3], abr[0] + 60, abr[1])
out.append(f'<text x="{wp[0] + wp[2] + 30}" y="{wp[1] + wp[3] + 20}" font-size="11" fill="{MUTED}">abpmer_result</text>')
arrow(*R(pr), *L(cr))
arrow(*R(cr), *L(pkr))
arrow(prj[0] + prj[2] / 2, prj[1] + prj[3], *T(pr), "POST /api/run", dashed=True)

H = y3 + 190
out.append(f'<text x="40" y="{H - 20}" font-size="12" fill="{MUTED}">API: GET /api/sample · POST /api/run · POST /api/rpl · '
           f'POST /api/abpmer/export · POST /api/abpmer/import · POST /api/hindcast. Example ABPmer files and uploaded RPLs/results are git-ignored.</text>')

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
       f'font-family="system-ui, -apple-system, Segoe UI, sans-serif">'
       f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
       f'<path d="M0,0 L10,5 L0,10 z" fill="{INK2}"/></marker></defs>'
       f'<rect width="{W}" height="{H}" fill="{BG}"/>' + "".join(out) + "</svg>")
dst = pathlib.Path(sys.argv[1])
dst.with_suffix(".svg").write_text(svg)
dst.with_suffix(".html").write_text(f"<!doctype html><meta charset=utf-8><body style='margin:0'>{svg}</body>")
print(W, H)
