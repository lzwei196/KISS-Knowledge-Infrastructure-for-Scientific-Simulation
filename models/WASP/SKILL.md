> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> **WASP default route (2026-10-07):** the model is US EPA WASP 8.5.0 (`waspccli.exe`) run under
> WINE. Build cases with `tools/build_wasp_lake_case.py` (or `tools/wasp_wif_api.py`), run them with
> `tools/run_wasp_engine.py`, read them with `tools/parse_wasp_engine_output.py`. The older
> `tools/run_wasp.py`, `convert_forcing_to_wasp.py`, `convert_parameters_to_wasp.py` and
> `parse_output_wasp.py` are an analytic Python **SURROGATE**, not EPA WASP. Never run the surrogate
> in place of the engine; if the engine is missing, report that. Use the surrogate only when a task
> explicitly asks for it and label its numbers "surrogate".
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong (model crashes, wrong output,
> unexpected values), follow this order. Do NOT skip steps or write debug scripts:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — Check the model's own documentation (PDF manual, README,
>    official examples) for expected input formats, variable names, and units
> 3. **Find working examples** — Look in `outputs/` for previous successful runs of
>    this model, or check if the model ships with test/example data
> 4. **Fix the tool** — Now that you know what "correct" looks like, make targeted fixes
>
> Resist the urge to write diagnostic/debug Python scripts. The answers are
> almost always in the official docs and working examples, not in reverse-engineering the binary.

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (10 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (43 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (16 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |
| what past runs learned | `.kdt_evolution.jsonl` | append-only memory of previous runs and fixes on this KI. |

*Projected 2026-10-07 from the KI's actual contents — 10 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_wasp_lake_case.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_wasp_lake_case.py --help` |
| `tools/build_wasp_weather_from_source.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_wasp_weather_from_source.py --help` |
| `tools/convert_forcing_to_wasp.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_wasp.py --help` |
| `tools/convert_parameters_to_wasp.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_parameters_to_wasp.py --help` |
| `tools/parse_output_wasp.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output_wasp.py --help` |
| `tools/parse_wasp_engine_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_wasp_engine_output.py --help` |
| `tools/prepare_wqp_lake_obs.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/prepare_wqp_lake_obs.py --help` |
| `tools/run_wasp.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_wasp.py --help` |
| `tools/run_wasp_engine.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_wasp_engine.py --help` |
| `tools/wasp_wif_api.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/wasp_wif_api.py --help` |

*10 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# WASP -- Knowledge Infrastructure Skill Document

> **Version**: EPA WASP 8.5.0 (real engine) + legacy analytic surrogate
> **Domain**: surface-water quality (rivers, lakes, reservoirs, estuaries)
> **Last updated**: 2026-10-07
> **Validation status**: official EPA example reproduced exactly; one real case (Lake Erie Central
> Basin, validation - nothing calibrated): water temperature very good (NSE 0.99), DO (all data)
> below the bar (NSE −0.01) - the deck has no algae/nutrients (not configured yet)

---

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | Water Quality Analysis Simulation Program (WASP), US EPA |
| Version | 8.5.0 — banner "Wasp suite version 8.5.0, Gui develop af12325 dirty, Model master e86fb43" |
| Language | closed-source Windows binaries (Fortran/C++); no public source repository |
| License | US EPA public release (US Government work) |
| Installer | `wasp-version-8.5.0-install-64-bit-10-25-2025.exe` (epa.gov), sha256 `2bb410b59ead76d5ba3681f05f61c4b1193a1be8b5393ab7a33f234957b293d4` |
| Engine on this server | `C:\WASP8\wasp\bin\waspccli.exe` in WINE prefix `KISSPATH_HOME/engine_builds_20261006/wasp/wineprefix` (WINE 9.0); launcher in the models DB: `KISSPATH_HOME/engine_builds_20261006/wasp/run_wasp.sh` |
| Engine elsewhere (a copy of this KI) | every tool finds the prefix by `--wineprefix` → `$WASP_WINEPREFIX` → `$WASP_ENGINE_ROOT/wineprefix` → the server path above; wine by `--wine` → `$WASP_WINE` → PATH. Other paths: `$WASP_WQP_DIR` (WQP obs), `$KI_TOOLS_COMMON`, `$WASP_CMFD_DIR`, `$KI_PYTHON` (preflight interpreter), `$WASP_LAUNCHER` |
| Other EPA programs used | `wasptool.exe` (.wif data API), `BMD2_Extract.exe` (results to CSV) |
| Citation | US EPA ORD WASP8 documentation (Wool, Ambrose et al.) (https://www.epa.gov/hydrowq/wasp-model-documentation) |
| Primary domain | water quality: DO, CBOD, nutrients, algae, temperature, solids, toxicants |
| Spatial mode | network of well-mixed segments (0-D boxes linked by flows); the KI builds lake boxes |

Build provenance: `KISSPATH_HOME/engine_builds_20261006/wasp/BUILD_LOG.md` (headless Qt installer
under WINE; no compilation possible — EPA ships binaries only).

---

## 2. What This Model Does

WASP solves mass balances for water-quality "systems" (DO, CBOD, nutrients, phytoplankton, solids,
temperature, toxicants…) in a network of segments, with transport set by one of several flow
options (stream routing, kinematic wave, flow routing, ponded weir, Lake 1D-vertical, dynamic) and
kinetics set by the chosen model library (here: Advanced Eutrophication, `multi-algae.dll`, with
the heat module). Water temperature comes from a full surface heat balance driven by weather
time functions; DO from reaeration toward a temperature- and pressure-dependent saturation minus
CBOD decay, SOD and (when configured) algal respiration plus photosynthesis.

What the KI can do with the real engine today: run any EPA `.wif`; edit any value of a `.wif`
through EPA's own API; build a well-mixed lake-box case with real weather; score DO and water
temperature against WQP lake observations. Not yet: building segment networks for rivers,
layered lake decks, nutrient/algae systems, calibration loops on the engine.

---

## 3. Input Requirements

**Exact shapes live in `docs/format_spec.yaml`** (projected from dag + triplets). The full
preparation plan, with every parameter, its API keyword and its source, is
`docs/input_preparation.md`.

WASP 8.5 has no text input: one binary `.wif` holds the whole case. The KI never writes a `.wif`
from scratch — it copies EPA's `SteadyState.wif` (`test_cases/steady_state/inputs/`, sha256
`41a3178f…`) and changes listed values through `wasptool.exe`.

### 3.1 Meteorological Forcing
Daily weather time functions (days relative to the run start), from
`tools/build_wasp_weather_from_source.py` (`load_daily_forcing` → NASA POWER / CMFD / MSWX):

| WASP time function (ISC) | Unit | Source |
|---|---|---|
| Solar Radiation - 1 (4) | W/m² daily mean | `srad_wm2` |
| Air Temperature Function 1 (17) | °C | `temp_mean_c` |
| Dew Point Function 1 (29) | °C | Magnus inverse of `shum_kgkg`, `pres_pa` |
| Wind Speed Function 1 (21) | m/s at 10 m | `wind_ms` |
| Cloud Cover Function 1 (25) | **0–1 fraction** | Kasten–Czeplak inverse of Rs / FAO-56 Rso |

### 3.2 Static Inputs
Segment depth and volume, elevation (constant 57 + segment parameter 24; DO saturation pressure),
latitude/longitude (constants 2/3), SOD (segment parameter 32, g O₂/m²/d), CBOD decay (constant
47), initial concentrations per system. Data source of the Lake Erie case: depth 12 m from the
GLNPO August temperature profiles, elevation 174 m.

### 3.3 Configuration Files
Only the `.wif`. Every value written must also have its **"used" flag = 1** or the engine
ignores it (dt_wasp_027). `build_wasp_lake_case.py` writes the full API command list next to the
case so every edit is auditable.

---

## 4. Build Instructions

Nothing to compile. The engine is installed (do not change the build):
```bash
export WINEPREFIX=KISSPATH_HOME/engine_builds_20261006/wasp/wineprefix WINEARCH=win64 WINEDEBUG=-all
unset DISPLAY
wineboot -i
wine wasp-version-8.5.0-install-64-bit-10-25-2025.exe --root 'C:\WASP8' --accept-licenses \
     --accept-obligations --default-answer --confirm-command install
```
(epa.gov downloads work through proxy 127.0.0.1:7877.) Python side: `requirements.txt`
(numpy, pandas, scipy, matplotlib, requests, PyYAML) plus `ki_tools_common`. Set `KI_PYTHON` to
the interpreter that has them.

---

## 5. Execution

```bash
# official regression test (EPA Steady State example) — exit 0 = PASS
python test_cases/steady_state/run_reference.py

# any .wif
python tools/run_wasp_engine.py --wif model.wif --run-dir run1 --extract-all
python tools/run_wasp_engine.py --list-variables run1/model.BMD2

# the Lake Erie real case, tool by tool (weather -> case -> engine -> obs -> scores)
python tools/build_wasp_weather_from_source.py --source nasa_power --lat 41.95 --lon -81.55 \
    --start 2004-01-01 --end 2014-12-31 --elev 174 --out weather_nasa_power.csv
python tools/build_wasp_lake_case.py --weather weather_nasa_power.csv --start 2004-01-01 \
    --end 2014-12-31 --depth 12 --lat 41.95 --lon -81.55 --elev 174 --sod 0 --do0 13.0 --temp0 2.0 \
    --out-dir case --name erie_cb_surface
python tools/run_wasp_engine.py --wif case/erie_cb_surface.wif --run-dir run \
    --extract "Dissolved Oxygen" --extract "Water Temperature" --extract "Total CBOD" --segments 1
# then the two prepare_wqp_lake_obs.py calls and parse_wasp_engine_output.py of docs/s4_output_parsing.md
```
On this server the same chain is wrapped by `KISSPATH_KI_ROOT/WASP/run_and_score.py`
(outside the KI; it calls these tools).
`run_wasp_engine.py` counts a run as good only with the close-out line, fresh `.OUT`/`.BMD2`, a
valid BMD2 header and no unexpected ERROR line; the wine exit code is ignored (it is 2 on good
runs). Exit codes: 0 ok, 1 failed, 2 bad command line, 3 WINE/engine missing.

**Expected runtime**: official example 3.4 s; Lake Erie 10-box case 28 s for 11 years
(about 2.6 s per simulated year); case build 8 s; whole runner 42 s (weather reused).

---

## 6. Output Description

Restated from `dag.yaml` (the dag wins if they disagree).

**Headline output** (`validation_rank: 1`):

> `do_timeseries` — Dissolved-oxygen concentration time series in lake/river surface water per
> segment (WASP 8.5), daily mean of the BMD2 variable 'Dissolved Oxygen'. (mg/L)

| Output variable (dag `var`) | rank | File | Unit | Medium | Produced by the real-engine route? |
|---|---|---|---|---|---|
| `do_timeseries` | 1 | `<model>.BMD2` "Dissolved Oxygen" | mg/L | lake/river surface water | yes |
| `do_profile` | 2 | — | mg/L | lake water column | **no** — needs a layered deck |
| `do_saturation` | 3 | computed by `parse_wasp_engine_output.py` | mg/L | surface water | yes (diagnostic) |
| `temperature_timeseries` | 4 | `<model>.BMD2` "Water Temperature" | °C | lake/river surface water | yes |
| `temperature_profile` | 5 | — | °C | lake water column | **no** — needs a layered deck |
| `TSI` | 6 | — | – | lake water | **no** — needs phytoplankton/TP systems |

The template deck's BMD2 also holds Total CBOD, DO diurnal average/min/max, Volume, Described
Sediment Oxygen Demand and Flow Out of Segment.

---

## 7. Tool Inventory

| Tool | Route | Purpose | Inputs | Outputs |
|---|---|---|---|---|
| `tools/run_wasp_engine.py` | REAL | run waspccli under WINE, judge success, extract BMD2 | `.wif` | run dir, extract CSV, summary JSON |
| `tools/wasp_wif_api.py` | REAL | get/put any `.wif` value through EPA's `wasptool.exe` | `.wif`, command list | edited `.wif`, JSON |
| `tools/build_wasp_weather_from_source.py` | REAL | weather time functions from the shared loader | lat/lon/dates/source | weather CSV |
| `tools/build_wasp_lake_case.py` | REAL | EPA template → lake-box case (hydraulics, site, kinetics, weather, used flags) | weather CSV, site values | `.wif`, commands, case JSON |
| `tools/prepare_wqp_lake_obs.py` | REAL (obs) | WQP lake obs: station typing, bbox, depth filter, whole-cruise DO sensor QC; one row per station-day with `value` (all data) and `value_qc` | WQP folder | station-day CSV + `<out>.cruise_qc.json` |
| `tools/parse_wasp_engine_output.py` | REAL | daily series, metrics (headline = all data `do_all`; QC subset `do_sensor_qc` reported next to it), DO-saturation diagnostic, figure | extract CSV, obs CSVs | CSVs, scores.json, PNG |
| `tools/run_wasp.py` | SURROGATE | analytic seasonal T/DO, profiles | JSON | JSON |
| `tools/convert_forcing_to_wasp.py` | SURROGATE | WQP/NLA → surrogate forcing JSON | CSVs | JSON |
| `tools/convert_parameters_to_wasp.py` | SURROGATE | lake presets → surrogate parameters | preset | JSON |
| `tools/parse_output_wasp.py` | SURROGATE | surrogate metrics, TSI | JSON | JSON/PNG |

Stage docs: `docs/s1_forcing_preparation.md`, `s2_parameter_setup.md` (API keyword table),
`s3_model_execution.md`, `s4_output_parsing.md` (real engine); `s5_calibration.md`,
`s6_tsi_analysis.md` (surrogate only).

### Shared Utilities (ki_tools_common)
`load_forcing.load_daily_forcing` (weather), `metrics.all_metrics` (keys `NSE`, `KGE`, `PBIAS`,
`RMSE`, `r`). `validation.validate_water_balance` does not apply: the lake box has no hydrology.

---

## 8. Unit Conversion Table

| Quantity | Loader / obs unit | WASP unit | Conversion |
|---|---|---|---|
| shortwave | W/m² daily mean | W/m² | none (MJ/m²/d ÷ 0.0864 if another source) |
| air temperature | °C | °C | none |
| humidity | kg/kg + Pa | dew point °C | e = q·p/(0.622+0.378q); Td = 243.04·ln(e/611.2)/(17.625−ln(e/611.2)) |
| wind | m/s at 10 m | m/s | none (do not use `wind2_ms`) |
| cloud | — | fraction 0–1 | from Rs/Rso; tenths/percent are WRONG (dt_wasp_029) |
| SOD | g O₂/m²/d | g/m²/d (param 32) | none |
| loads | kg/d | kg/d | — |
| WQP temperature | °C or °F per record | °C | °F → (x−32)·5/9 (prepare_wqp_lake_obs.py) |
| WQP DO | mg/L or % | mg/L | % saturation records dropped, never mixed |
| GLNPO depth | text "PRFL-15" | m | parsed from ResultCommentText |

## 8b. CMFD/MSWX Data Conventions
CMFD is China-only (Lake Erie uses NASA POWER). MSWX is global; the shared loader handles both
through the same `--source` switch. NASA POWER is always fetched live (`REALTIME=1`).

## 8c. Sign Conventions and Output Units
BMD2 concentrations are positive mg/L; temperature °C; volume m³; flow m³/s out of the segment;
"Described Sediment Oxygen Demand" g/m²/d (positive = uptake). Extract timestamps are
`MM/DD/YYYY HH:MM` (local model time, no time zone).

---

## 9. Diagnostic Triplets (Top 5)

Full corpus: `diagnostics/triplets.yaml` (43 entries; real-engine ones are dt_wasp_027–043).

| id | symptom | remedy |
|---|---|---|
| dt_wasp_027 | value set through the API but the run ignores it | set the "used" flag (`PPARAMISUSED`/`PCONSTISUSED`/`PTFISUSED`) |
| dt_wasp_029 | water at 45–70 °C, or the engine never finishes | cloud cover as a 0–1 fraction |
| dt_wasp_035 | lake model scored against river samples | `prepare_wqp_lake_obs.py --site-types "Great Lake"` |
| dt_wasp_041 | whole GLNPO cruises with a dead (or suspect) DO sensor | cruise QC in `prepare_wqp_lake_obs.py`: only proven faults excluded; headline stays all data (`do_all`) |
| dt_wasp_042 | simulated DO stays at ~1.03 × saturation | deck has no algae/nutrients (not configured yet); report as a limit, do not tune |
| dt_wasp_040 | surrogate numbers quoted as WASP | use the real-engine route; label surrogate output |

---

## 10. Coupling Interfaces

- Input side: any tool that writes the weather CSV schema of s1 can drive the heat module; flows
  and boundary concentrations are API series (`PNOQFUNC`, `PBOUNDFUNC`) — a watershed model's
  discharge and loads can be written the same way (not built yet).
- Output side: `<model>_extract.csv` / `sim_daily_seg<N>.csv` (daily means per variable).
- WASP itself also reads hydrodynamic linkage files (EFDC/HYD, flow option 3) — not used by the KI.

---

## 11. Validated Results

### 11.1 Official example (engine repeat test)
EPA Steady State example (`test_cases/steady_state/`), 2026-10-07 through `run_wasp_engine.py`:
closed out in 3.4 s, 10 segments, 9 variables, 355 output times, DO end seg 1 = 7.234781 mg/L,
seg 9 = 5.7412233, CBOD seg 1 = 105.90371, temperature seg 9 = 21.372213 °C — identical to the
2026-10-06 build log run. **PASS (exact).** This is a repeat-run check, not a physical validation
(EPA ships no reference output).

### 11.2 Real case: Lake Erie Central Basin surface layer (validation, nothing calibrated)

| Property | Value |
|----------|-------|
| Engine | EPA WASP 8.5.0 `waspccli.exe` under WINE through `tools/run_wasp_engine.py` (closed out, 0 unexpected ERROR lines) |
| Location | box at 41.95 N, 81.55 W; obs = 11 EPA GLNPO "Great Lake" stations (ER30, ER31, ER32, ER36, ER37, ER38, ER42, ER43, ER73, ER78M, ER95B) in bbox −82.5…−80.4 E, 41.35…42.6 N |
| Model setup | EPA Steady State deck edited through EPA's API: 10 identical isolated boxes, 12 m deep, Flow Routing; segment 1 scored; systems CBOD, DO, solids, water temperature only (no algae, no nutrients, SOD 0) |
| Period | 2004 spin-up; scored 2005–2014 |
| Forcing | NASA POWER daily (live), `build_wasp_weather_from_source.py` |
| Obs | WQP `wqp_lakes` Lake_Erie_Central, samples ≤ 5 m, one row per station-day (176 DO, 197 temperature rows; April and August cruises only) |
| Calibration | **none** — every value is an engine default, a literature value or read from the data (depth 12 m = August mixed-layer depth from GLNPO profiles). These are validation numbers. |
| Run | `KISSPATH_KI_ROOT/WASP/detached/real_case/c5fa2a53d2794a7c82a8b5ba157f79f0/` (re-scored 2026-10-07 with the corrected obs QC; a rebuild of the case through the current tools gave a byte-identical extract) |

### Performance Metrics — judged against the field's bar, not intuition

> Bar for `do_timeseries` and `temperature_timeseries` (NSE, per `arnold2012`, `efdc2021`,
> `deepavarsa2023`, `piccolroaz2013` in `docs/validation_convention.yaml`): satisfactory ≥ 0.5,
> good: no cited threshold, very good ≥ 0.75.
> Headline `do_timeseries`, all data (176 station-days): **NSE −0.01 → below the bar (not validated)**.
> Water temperature (197 station-days): **NSE 0.99 → very good**.

| Variable | Rows | NSE | KGE | PBIAS (%) | r | RMSE | Note |
|---|---|---|---|---|---|---|---|
| `do_timeseries`, all data (headline) | 176 | −0.011 | 0.605 | +20.0 | 0.671 | 2.91 mg/L | per-station median NSE −0.014 (11 stations) |
| `do_timeseries`, cruise-QC subset | 176 | −0.011 | 0.605 | +20.0 | 0.671 | 2.91 mg/L | same rows: the only excluded cruises (dead sensors) have no in-range values |
| `temperature_timeseries` | 197 | 0.992 | 0.953 | +2.8 | 0.997 | 0.96 °C | per-station median NSE 0.992 |

The same run scored against the per-day network mean (`--network-mean`, support changes from day
to day) gives DO NSE −0.207 (n 30) and temperature 0.994 (n 33).

Cruise QC on this data (from the cruise's own data, never from the model; dt_wasp_041):
- EXCLUDED (sensor proven wrong): 2009-08 and 2010-04 (`sensor_dead`: every DO value negative;
  the range filter already removes them, so no scored row changes).
- DIAGNOSTIC only, data kept: 2012-04 and 2013-04 (whole column and surface at 37–39 % of
  saturation in a mixed April column), 2012-08 (19 %, stratified column) — `sat_offset_unconfirmed`;
  2005-04 and 2006-08 — `winkler_disagree_unmatched_depth` (CTD ≤ 5 m vs Winkler of unknown depth,
  ratio 0.72 and 1.35). A sensor fault is likely for some of these, but low DO alone, or a Winkler
  sample from an unknown depth, does not prove it, so they stay in the score.
- Sensitivity only (not a result): leaving the 5 diagnostic cruises out gives DO NSE 0.80,
  r 0.94, PBIAS +7.9 % (n 124). It shows how much these cruises drive the DO score.

Caveats, in plain words: the deck has **no algae and no nutrients** (not configured yet), so the
simulated DO stays at about 1.03 × saturation and cannot show algal supersaturation or depletion
(dt_wasp_042) — this explains much of the +20 % DO bias. Only April and August are observed, so
the seasonal contrast carries most of the score. The surrogate's older "Lake Erie" numbers (R =
0.885 temperature, 0.816 DO) were scored mostly against tributary stream samples (dt_wasp_035),
are not WASP results and are not comparable.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|---|---|---|---|
| Forcing | NASA POWER via shared loader | Validated (ranges) | dew point and cloud derived |
| Soil | — | n/a | no soil in a lake box |
| Land cover | — | n/a | |
| DEM / elevation | 174 m (lake level) | Set | used flag checked in .OUT echo |
| Initial conditions | climatological (DO 13, T 2 °C on Jan 1) | Pending | one spin-up year |
| Morphometry | depth 12 m from GLNPO August profiles | Set | single layer |

---

## 12. Parameter Selection by Region

> Not calibration — starting points.

| Situation | Key parameters | Rationale |
|---|---|---|
| Large temperate lake, surface layer | depth = summer mixed-layer depth (profiles), SOD 0, global Ka 0 (computed), CBOD 1 mg/L, decay 0.1/d | epilimnion has no sediment contact; wind reaeration dominates |
| Bottom layer / shallow lake | SOD 0.3–1.0 g O₂/m²/d (θ 1.04) | typical measured SOD range for Lake Erie sediments |
| High-altitude water body | elevation constant 57 + param 24 with used flags | DO × p/p0 (0.72 at 2700 m) |
| River reach | start from the EPA Steady State deck itself (kinematic wave, Ka 5/d) | the template is a river |

---

## 13. Known Limitations

- Lake-box case only: no stratification, no algae, no nutrients (not configured yet), so
  simulated DO stays near saturation (~1.03 ×, dt_wasp_042); `do_profile`,
  `temperature_profile` and `TSI` are not produced by the real-engine route yet.
- The shared `preflight_forcing.py` cannot identify a point NASA POWER CSV (dt_wasp_043); the
  weather tool's own validation is the check.
- No calibration loop on the engine; `s5_calibration.md` is surrogate-only.
- Template segments cannot be removed; unused ones are isolated (tiny flows).
- 31 missing time functions in the 2017 template (deposition, benthic fluxes) — expected.
- The print interval edit has no effect on BMD2 output frequency (dt_wasp_039).
- `BMD2_Extract.exe` has no published manual; the control layout in `run_wasp_engine.py` was
  found by testing.

## 14. Spinup Requirements

One year (2004) before scoring. The 12 m box forgets its initial temperature within weeks and
its initial DO within days (wind reaeration); CBOD (1 mg/L) decays away in a few months because
the box has no loads.

## 15. References

- US EPA WASP model documentation: heat-model.pdf, stream-transport-user-guide.pdf,
  wasp8_sod_module_v1.pdf, light-module.pdf (https://www.epa.gov/hydrowq/wasp-model-documentation)
- EPA WASP examples (https://www.epa.gov/hydrowq/wasp-model-examples) — Steady State example
- Literature behind the validation bands: `docs/gathered_papers.json`, `docs/papers_index.md`
- Alduchov & Eskridge (1996) Magnus formula; Allen et al. (1998) FAO-56 (Ra, Rso);
  Kasten & Czeplak (1980) cloud–radiation relation; APHA (1992) DO saturation

---

## Appendix A. SURROGATE (legacy analytic stand-in — NOT EPA WASP)

`tools/run_wasp.py` and its three helpers implement a sinusoidal seasonal temperature model, a
steady-state Streeter–Phelps seasonal DO, a logistic thermocline profile and Carlson TSI. They
were the whole KI until 2026-10-06. Use them only on explicit request; label results
"surrogate". Their how-to is in `docs/s5_calibration.md`, `docs/s6_tsi_analysis.md` and the
archived stage docs in `docs/surrogate/` (its I/O contract, the KI's dag.yaml until 2026-10-07, is
`docs/surrogate/surrogate_wasp_analytic_dag.yaml`; its old scores are kept apart in
`knowledge_infrastructure.yaml` → `validation.surrogate_metrics_not_wasp`); their known traps are
dt_wasp_001 – dt_wasp_026. Example (surrogate, for smoke tests only):
```bash
python tools/convert_parameters_to_wasp.py --lake-preset erie --output params.json
python tools/run_wasp.py --mode profile --params params.json --z-max 20 --z-step 1 --output profile.json
```
