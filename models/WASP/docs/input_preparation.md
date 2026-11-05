# WASP 8.5 — input preparation plan (real engine)

Written 2026-10-07 for the real EPA WASP 8.5 route. Sources: the engine's own data dictionary
(`C:\WASP8\wasp\etc\epa.sqlite`, tables `models`, `systems`, `constants`, `parameters`,
`time_functions`, `transport_options`), the `wasptool.exe` keyword table inside `waspcore.dll`,
EPA's WASP 8 module guides (heat-model.pdf, stream-transport-user-guide.pdf, wasp8_sod_module_v1.pdf
from https://www.epa.gov/hydrowq/wasp-model-documentation), the official Steady State example and
the `.OUT` echo of our own runs. The surrogate's inputs (JSON parameters) are in the old
`docs/s5_calibration.md` / `docs/s6_tsi_analysis.md` and are not repeated here.

## 0. What kind of model this is to prepare

WASP 8.5 has **no text input format**. Everything is in one binary `.wif` (boost-serialised).
Preparation therefore means: **copy a working `.wif`, then change specific values through EPA's
own data API** (`wasptool.exe`, wrapped by `tools/wasp_wif_api.py`). Nothing is generated from a
Python dict. The template is EPA's `SteadyState.wif` (Advanced Eutrophication, model type 11,
10 segments, systems: Upstream BOD, NPDES BOD (both CBODU), DO (DISOX), Solids (SOLID),
Temp (WTEMP)), shipped in `test_cases/steady_state/inputs/` (sha256 `41a3178f…`).

No Fortran fixed-width file is written by this KI, so the fixed-width template inspection step
does not apply. The `.OUT` file is the only human-readable echo of what the engine actually read —
check it after every new kind of edit (see §4).

## 1. Inputs and parameters

| # | Input / parameter | Unit the engine expects | Where it lives in the .wif (API keyword) | New case vs example | When data are missing |
|---|---|---|---|---|---|
| 1 | Run start | date | `PSEEDDATE m d y`, `PSEEDTIME h m s` | set to case start (example 2012-07-01) | required from user |
| 2 | Run length | days | `PENDJULIAN days` (relative to start) | set | required |
| 3 | Max time step | days | `PMAXDT d` | 0.05 for a lake box (example 0.014) | keep example value |
| 4 | Hydraulics option | code | `PIQOPT n`, `PFLOWTYPE seg n` | 7 = Flow Routing (volume/depth/velocity fixed) for a lake box; example 4 = kinematic wave | — |
| 5 | Segment depth | m | `PDMULT seg d` with `PDEXP seg 0`, `PINITIALDEPTH seg d` | observed mixed-layer depth (Lake Erie CB: 12 m from GLNPO Aug profiles) | from profiles; else HydroLAKES mean depth |
| 6 | Segment volume | m³ | `PVOLUME seg v` (= area × depth) | derived | — |
| 7 | Velocity | m/s | `PVMULT seg 0`, `PVEXP seg 0` | 0 in a lake | — |
| 8 | Flows | m³/s | `PNBRKQ fld fn n`, `PNOQFUNC fld fn k day q` | 1e-4 m³/s = boxes isolated | for rivers: gauge discharge (not built yet) |
| 9 | Boundary concentrations | system units | `PNBFP sys bc n`, `PBOUNDFUNC sys bc k day v` | = initial value (irrelevant at 1e-4 m³/s) | — |
| 10 | Initial concentrations | mg/L, °C | `PINITC sys seg v` | DO 13.0, T 2.0 (Jan 1), CBOD 1.0, solids 1.0 | climatology of the site's obs |
| 11 | Solar radiation | W/m² (daily mean) | time function ISC 4 (`PNBRKTF 4 1 n`, `PBRKTF 4 1 k day v`) + seg params 4 (mult 1) / 5 (TF 1) | NASA POWER | CMFD / MSWX via the same tool |
| 12 | Air temperature | °C | TF ISC 17 + seg params 2 / 3 | NASA POWER `temp_mean_c` | — |
| 13 | Dew point | °C | TF ISC 29 + seg params 10 / 11 | derived: Magnus inverse of `shum_kgkg`, `pres_pa` | — |
| 14 | Wind speed | m/s (10 m) | TF ISC 21 + seg params 6 / 7; param 13 sheltering 1.0 | NASA POWER `wind_ms`, height 10 m | — |
| 15 | Cloud cover | **0–1 fraction** | TF ISC 25 + seg params 8 / 9 | derived: Kasten–Czeplak inverse of Rs/Rso (FAO-56) | never tenths/percent (dt_wasp_029) |
| 16 | Elevation | m a.s.l. | constant 57 + seg param 24 | 174 m (Lake Erie) | DEM / HydroLAKES |
| 17 | Latitude / longitude | degrees | constants 2 / 3 | site | — |
| 18 | Sediment oxygen demand | g O₂/m²/d | seg param 32 (theta = constant 61) | 0 for an epilimnion box (no sediment contact in summer) | 0.3–1.0 for a bottom layer (literature) |
| 19 | CBOD decay | 1/d at 20 °C | constant 47 (one instance per CBOD system) | 0.1 | 0.05–0.3 |
| 20 | Global reaeration | 1/d | constant 55 | 0 = engine computes wind/hydraulic Ka | example uses 5.0 (river) |
| 21 | Ice switch | 0/1/2 | constant 501 | 0 (water stayed ≥ 0 °C in tests) | 1 for ice-cover studies |
| 22 | "used" flags | 0/1 | `PPARAMISUSED isc 1 1`, `PCONSTISUSED isc inst 1`, `PTFISUSED isc 1 1` | **must be 1 for every item set** | a 0 flag = value ignored (dt_wasp_027) |

Items 11–15, 16, 18 and the flags are what turns the EPA river example into a lake box; all are
applied by `tools/build_wasp_lake_case.py`, which writes the full command list next to the case.

### Unusual structure, stated plainly
- The template's 10 segments cannot be removed (`PNUMSEG 1` crashed the API on the next flow
  query). The builder keeps all 10 as identical, hydraulically isolated boxes and scores segment 1.
- Time series are stored as absolute dates and written as days relative to the seed date, so
  the seed date is set first (dt_wasp_030).
- The template has 31 time functions missing (atmospheric deposition, benthic fluxes); 8.5 prints
  "Failed to locate time function" 31 times. Expected, counted by `run_wasp_engine.py`.
- Systems not in the template (nutrients, phytoplankton, pH…) are not configured — the engine
  supports them, but no tool adds systems yet (TSI and algae-driven DO are out of scope).

## 2. Shared-library schema — verified by calling it (2026-10-07)

```python
from ki_tools_common.load_forcing import load_daily_forcing
d = load_daily_forcing('nasa_power', 41.9, -81.6, 2014, 2014)
sorted(d) == ['dates','lrad_wm2','precip_mm','pres_pa','shum_kgkg','srad_wm2','temp_max_c',
              'temp_mean_c','temp_min_c','wind2_ms','wind_height_m','wind_ms']
# dates ndarray datetime64[D] (365,);  srad_wm2 daily mean W/m2 (13.7..355, mean 149.8)
# temp_mean_c -17.4..24.9;  wind_ms 1.35..15.65 at wind_height_m = 10.0;  wind2_ms = 2 m
# shum_kgkg 0.00086..0.0166;  pres_pa 97460..101460;  no dew point, no cloud cover
```
`ki_tools_common.metrics.all_metrics(obs, sim, dates=...)` returns keys `NSE`, `KGE`, `PBIAS`,
`RMSE` (UPPER case) and `r`.

`validate_water_balance` is **not applicable**: the lake-box case has no hydrology (flows are
1e-4 m³/s, volume fixed). The physical-plausibility checks are `validate_outputs()` in the weather
tool and the engine's own mass-balance/close-out checks in `run_wasp_engine.py`.

## 3. Observations (for validation, not input)

`wqp_lakes` binding → `KISSPATH_OBS/water_quality/wqp/<lake>/` on this server
(another copy: `--wqp-dir` or `$WASP_WQP_DIR`).
For Lake_Erie_Central the folder is mostly tributary streams (dt_wasp_035) and GLNPO values have
their depth only in `ResultCommentText` (dt_wasp_036). `tools/prepare_wqp_lake_obs.py` resolves
station type and coordinates through the WQP Station service, keeps "Great Lake" stations in a
bbox, keeps samples ≤ `--max-depth-m`, runs a whole-cruise DO sensor QC (dt_wasp_041) and writes
ONE row per station-day with two values: `value` (all data) and `value_qc` (cruises with an excluding
sensor flag left out). `--network-mean` writes a per-day mean over stations instead (its support
changes from day to day, so it is labelled `network_mean_variable`).

## 4. How to check an edit actually reached the engine

1. `python tools/wasp_wif_api.py --wif case.wif --get "GPARAMISUSED 32 1" ...` (flag = 1)
2. run, then `tr -d '\000' < run/<model>.OUT | less` — "Segment Parameters", "Constants &
   Kinetics" and "Environmental Time Functions" list only what the engine will use.
3. a sensitivity probe for anything new (e.g. elevation 0 vs 2700 m changed DO × 0.724).

## 5. Capability → tool map

| Capability | Tool |
|---|---|
| read/edit any .wif value through EPA's API | `tools/wasp_wif_api.py` |
| weather forcing (heat balance, wind reaeration) | `tools/build_wasp_weather_from_source.py` |
| lake-box case from the EPA template (hydraulics, site, kinetics, SOD, ICs, weather) | `tools/build_wasp_lake_case.py` |
| real engine run + BMD2 extraction | `tools/run_wasp_engine.py` |
| lake observations (station typing, depth filter, cruise sensor QC, station-day rows) | `tools/prepare_wqp_lake_obs.py` |
| output parsing, DO saturation, metrics, figure | `tools/parse_wasp_engine_output.py` |
| analytic SURROGATE (not WASP) | `run_wasp.py`, `convert_forcing_to_wasp.py`, `convert_parameters_to_wasp.py`, `parse_output_wasp.py` |
