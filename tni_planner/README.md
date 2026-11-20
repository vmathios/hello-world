# T&I Concept Planner (MVP)

Builds offshore-wind **transport & installation (T&I) concepts** end-to-end: define concepts
(ports, vessels, work packages) → weather-downtime simulation → **P50 schedule (Gantt)** and
**cost comparison** across concepts. It replaces the Excel chain: downtime tool → cost tool → Gantt.

![screenshot](docs/screenshot.png)

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
4. **Schedule & cost**: packages are chained on P50 finishes. Cost = vessel day rate × P50 days +
   mob/demob (once per vessel) + port day rate × P50 days + port fixed cost (once per port) + extras.

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
- `POST /api/abpmer/export` – `{project, concept, package, mode}` → ABPmer input `.xlsx`
- `POST /api/abpmer/import` – ABPmer RESULT `.xlsx` → `{id, operation, net_days, by_week}`

All numbers in the sample (rates, limits, durations) are illustrative placeholders.
