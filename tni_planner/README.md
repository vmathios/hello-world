# T&I Concept Planner (MVP)

Builds offshore-wind **transport & installation (T&I) concepts** end-to-end: define concepts
(ports, vessels, work packages) → weather-downtime simulation → **P50 schedule (Gantt)** and
**cost comparison** across concepts. It replaces the Excel chain: downtime tool → cost tool → Gantt.

![screenshot](docs/screenshot.png)

Workflow & data model: [docs/architecture.png](docs/architecture.png)
(regenerate: `python3 docs/make_diagram.py /tmp/arch && node docs/render_png.js /tmp/arch.html docs/architecture.png 1640 1398`)

## Run
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload      # open http://localhost:8000
pytest -q
```

## How it works
1. **Input** (`data/sample_project.json`): site coordinates, number of components, and one or more
   concepts. Each concept has ports (coordinates, day rates, fixed upgrade cost), vessels (speed,
   day rate, mob/demob, deck capacity) and **work packages** (e.g. monopiles, array cables, WTGs).
   Ports and vessels carry what the schedule and CAPEX need (location; speed, day rate, deck capacity).
   A work package has load-out steps at port and installation steps at site, each with a duration and
   weather limits (Hs, wind), transit limits, and a fixed start date or a dependency (`after` + `lag_days`).
2. **Sequence builder** (`app/engine.py`): expands each package into a full activity sequence
   (load units → transit out (distance port→site ÷ speed) → install each unit / move infield → transit back)
   × number of trips (`ceil(quantity / deck_capacity)`).
3. **Weather downtime engine** (`app/weather.py`): a pluggable interface, `simulate(steps, start, years)`.
   - `synthetic`: built-in persistence simulation on a generated North-Sea-like hindcast (demo only).
   - `csv:<path>`: the same simulation on your own hourly hindcast (`time,hs,ws` CSV, upload it in the UI).
   - `external`: HTTP adapter for a third-party downtime tool (`TNI_EXTERNAL_URL`, `TNI_EXTERNAL_TOKEN`).
     Adapt `_to_payload` / `_from_response` to that tool's API.
   Each step is non-splittable and needs a continuous workable window; the sequence is simulated for each
   hindcast year from the same calendar start date, giving P10/P50/P90 durations.
4. **Schedule & cost**: packages are chained on P50 finishes. MVP CAPEX = **vessel day rate × P50 duration**,
   shown per component. (Fuel, CO2 tax, specialist equipment and service contracts are planned as separate
   cost datasets in a later version.)

## Route Position List (cable packages)
**Load RPL ↑** on a package uploads a CSV with one row per route point (installation order):

| column | |
|---|---|
| `cable_id` | required (aliases: cable, route, id) |
| `lat`, `lon` | WGS84 – or `easting`, `northing` plus the EPSG code (asked on upload, e.g. 32631) |
| `kp` | optional; if present, length = KP range, else route geometry |
| `from`, `to` | optional asset names |

With an RPL each cable is one unit: the quantity becomes the number of cables, steps are placed at the
cable's first or second end (`position: start | end`), rate-based steps such as freelay use
`rate_m_per_h` × route length, transits go to/from the actual cable ends and infield moves use the
distance between consecutive cables at `infield_speed_kn`. The ABPmer export then lists every cable
with its own coordinates. Sample: `data/samples/sample-demo-iac.csv` (dummy layout, 60 cables).

## ABPmer workflow
In **Work package detail**, each package has two buttons:
1. **ABPmer input ↓** – downloads the task-list workbook in the ABPmer template layout (task name,
   lon/lat, task duration, weather window = duration × `contingency_factor`, Hs, Uw,10 at 10 m / 600 s,
   Uc, "group with following task", daylight flag, survival limit row). If the quantity divides evenly
   into trips, one trip cycle is exported with "repeat N times"; otherwise every trip is listed.
2. **Import result ↑** – upload the RESULT workbook you get back. The planner reads the
   *Whole Operation* sheet (total duration per probability of non-exceedance × 52 weekly start dates),
   stores it under `data/abpmer_results/`, links it to the package (`"abpmer_result": "<id>"`) and
   re-runs. P10/P50/P90 then come from ABPmer, interpolated to the package's actual start date.
   A warning appears if ABPmer's net duration differs from the planner's Pnet by more than 10%.
   **Use simulation** unlinks it.

Step fields used for ABPmer: `duration_h`, `window_h` (optional override), `limits.hs_max`,
`limits.ws_max` (Uw,10), `limits.uc_max` (Uc), `group_with_next`, `daylight_only`; package fields
`contingency_factor` (default 1.5) and `survival_limit` (default Hs 3.5 m / 24 h).
The built-in simulation also uses weather windows and grouped tasks; it ignores Uc (no current data in the synthetic hindcast).

Real ABPmer example files can be kept in `data/abpmer_examples/` – this folder is git-ignored, as are
imported results, so project data never reaches the (public) repository. `tests/test_abpmer.py` uses
the example result when it is present.

## API
- `GET /api/sample` – example project
- `POST /api/run` – project JSON → per-concept, per-package P10/P50/P90, dates, costs
- `POST /api/hindcast` – upload hindcast CSV → `weather` key to use
- `POST /api/rpl` – RPL CSV (+ optional `epsg`) → `{id, cables, total_km}`
- `POST /api/abpmer/export` – `{project, concept, package, mode}` → ABPmer input `.xlsx`
- `POST /api/abpmer/import` – ABPmer RESULT `.xlsx` → `{id, operation, net_days, by_week}`

All numbers in the sample (rates, limits, durations) are illustrative placeholders.
