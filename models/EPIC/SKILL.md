---
name: epic
description: >-
  EPIC 1102. Covers Crop/plant growth and yield (~80-150 crop types, one growth model with
  per-crop parameters); Field hydrology (NRCS curve-number runoff, percolation, lateral
  flow, ET); Water erosion (MUSLE/USLE/MUSS/MUST/RUSLE family) and wind erosion; Nutrient
  cycling (N, P, K) with leaching, volatilization, denitrification; Soil organic carbon
  dynamics (CENTURY sub-model). Use when the task involves running, configuring,
  calibrating or interpreting EPIC.
---

> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual EPIC1102 binary** (`epic1102-official_release.exe`)
> for any run described in this document. EPIC is closed-source Fortran; a
> Python reimplementation would not reproduce its crop growth, CENTURY soil
> organic matter, MUSLE erosion, or denitrification modules.
>
> If the model fails to execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the EPIC binary, Wine, and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong (model crashes, wrong output,
> unexpected values), follow this order. Do NOT skip steps or write debug scripts:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — Check the model's own documentation (PDF manual, README,
>    official examples) for expected input formats, variable names, and units
> 3. **Find working examples** — Look in `templates/` for the shipped
>    `epic1102_example_files_20221002` workspace, or in `outputs/` for previous
>    successful runs
> 4. **Fix the tool** — Now that you know what "correct" looks like, make targeted fixes
>
> Resist the urge to write diagnostic/debug Python scripts. The answers are almost
> always in the official examples, not in reverse-engineering the binary.

---

# EPIC 1102 — Environmental Policy Integrated Climate

EPIC (Environmental Policy Integrated Climate; formerly Erosion-Productivity
Impact Calculator) is a field-scale agro-ecosystem model developed by the
USDA/Texas A&M Blackland Research Center. It simulates, on a daily time step,
the complete land-atmosphere interaction of a cropped (or natural-vegetation)
field: weather, hydrology, soil erosion, nutrient cycling, pesticide fate,
plant growth, tillage, and management economics.

This knowledge infrastructure wraps the **EPIC 1102 official release** (Win32
console executable, v2025-05-25) with copy-first Python tools that preserve
Fortran fixed-format files, a CMFD/NASA-POWER forcing adapter, an HWSD soil
adapter, and output parsers for the model's annual/daily text files.

## Model overview

| Attribute              | Value                                             |
|------------------------|---------------------------------------------------|
| Name                   | EPIC 1102                                         |
| Version                | v2025-05-25 (official release)                    |
| Domain                 | agro-ecosystem / soil-crop-water/nutrient         |
| Scale                  | field (point); up to 10 soil layers               |
| Time step              | daily (sub-daily sediment routing)                |
| Language               | Fortran (compiled to PE32 Windows console EXE)    |
| Execution on Linux     | via Wine                                          |
| Source                 | closed binary; example workspace included         |
| Primary reference      | Sharpley & Williams (1990); Williams (1995)       |
| Binary                 | `epic1102-official_release.exe`                   |

Working workspace used for this KI:
`KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent/_work_v2/EPIC/epic_workspace`

## Installation / environment

EPIC 1102 is distributed as a precompiled Windows console executable. On this
HydroCraft server it is launched under Wine.

```bash
which wine                                                      # must resolve
ls KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent/_work_v2/EPIC/epic_workspace/epic1102-official_release.exe
wine /path/to/epic1102-official_release.exe                     # runs in CWD
```

All input files must live **in the current working directory** when the
executable is launched — EPIC reads by hard-coded filename from CWD.

## Pipeline stages

```
┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
│ 1. SITE PREPARATION  │───▶│ 2. FORCING           │───▶│ 3. SOIL + LANDUSE    │
│  lat/lon/elev/slope  │    │  CMFD→.DLY,.WP1,.WND │    │  HWSD → .SOL         │
│  → umstead.SIT       │    │                      │    │                      │
└──────────────────────┘    └──────────────────────┘    └──────────────────────┘
           │                           │                           │
           ▼                           ▼                           ▼
┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
│ 4. OPERATIONS (.OPC) │───▶│ 5. CONTROL FILES     │───▶│ 6. RUN EPIC (wine)   │
│  plant/fert/harvest  │    │  RUN/CONT/list-COMs  │    │  epic1102-...exe     │
│  crop code from DB   │    │                      │    │                      │
└──────────────────────┘    └──────────────────────┘    └──────────────────────┘
                                                                    │
                                                                    ▼
                                                    ┌──────────────────────────┐
                                                    │ 7. PARSE OUTPUTS         │
                                                    │  .ACY yield, .ANN wbal   │
                                                    │  → CSV + validation      │
                                                    └──────────────────────────┘
```

## Input files (copy-first — NEVER regenerate from scratch)

EPIC uses **fixed-width Fortran-formatted** files where column position is
load-bearing. A single misaligned digit causes silent wrong-result failures.

| File              | Purpose                                      | Template in |
|-------------------|----------------------------------------------|-------------|
| `EPICRUN.DAT`     | Run list: site_id, indexes into each list    | templates/  |
| `EPICCONT.DAT`    | Simulation control (years, flags, params)    | templates/  |
| `EPICFILE.DAT`    | Names of database files                      | templates/  |
| `SITECOM.DAT`     | List of `.SIT` files (index → filename)      | templates/  |
| `SOILCOM.DAT`     | List of `.SOL` files                         | templates/  |
| `OPSCCOM.DAT`     | List of `.OPC` operation schedules           | templates/  |
| `WPM1USEL.DAT`    | List of `.WP1` monthly weather stats         | templates/  |
| `WINDUSEL.DAT`    | List of `.WND` wind stats                    | templates/  |
| `WDLSTCOM.DAT`    | List of `.DLY` daily weather files           | templates/  |
| `CROPCOM.DAT`     | Crop parameter database (58 cols, 150+ crops)| templates/  |
| `FERT2012.DAT`    | Fertilizer database                          | templates/  |
| `TILLCOM.DAT`     | Tillage implement database                   | templates/  |
| `PESTCOM.DAT`     | Pesticide database                           | templates/  |
| `PARM1102.DAT`    | Global model parameters                      | templates/  |
| `MLRN1102.DAT`    | MLRN machine-learning-N parameters           | templates/  |
| `PRNT1102.DAT`    | Output variable selection / print flags      | templates/  |
| `<site>.SIT`      | Site: lat, lon, elev, slope, CO2             | per run     |
| `<site>.SOL`      | Soil profile (up to 10 layers, 40+ props)    | per run     |
| `<site>.OPC`      | Operation schedule (plant/fert/till/harvest) | per run     |
| `<stn>.DLY`       | Daily weather: yr mo dy RAD TMX TMN PRCP RHUM WSPD |  per run|
| `<stn>.WP1`       | Monthly mean weather (for generator backfill)| per run     |
| `<stn>.WND`       | Monthly wind                                 | per run     |

## Output files

| File         | Content                                                      |
|--------------|--------------------------------------------------------------|
| `*.OUT`      | Main human-readable run log (echo + variable names + summaries)|
| `*.ACY`      | Annual crop yield: YR RT# CPNM YLDG YLDF WCYD HI BIOM RW YLN YLP YLC …|
| `*.ANN`      | Annual summary: YR AP15 PMTE TMX TMN PRCP IRGA PET ET Q DN LIME DN2O FULU|
| `*.DWC`      | Daily water cycle                                            |
| `*.DCN`      | Daily C/N cycle                                              |
| `*.DGN`      | Daily general                                                |
| `*.ACN`      | Annual C and N                                               |
| `*.ASL`      | Annual soil layer                                            |
| `*.MFS`      | Monthly flood sediment                                       |

## Unit trap table (verified empirically)

| Variable      | Model unit     | CMFD/NASA unit    | Conversion       |
|---------------|----------------|-------------------|------------------|
| Precipitation | mm/day         | kg m-2 s-1 (CMFD) | × 86400          |
| Tmax / Tmin   | degC           | K (CMFD), degC (POWER) | − 273.15 (CMFD only)|
| Radiation     | MJ m-2 day-1   | W m-2 (CMFD srad) | × 0.0864         |
| Rel. humidity | fraction 0-1   | % (MERRA2)        | × 0.01           |
| Wind speed    | m/s            | m/s (CMFD,MSWX)   | identity         |
| Elevation     | m              | m (HWSD DEM)      | identity         |
| Slope         | m/m            | m/m (SRTM)        | identity         |
| Soil bulk density | t/m3       | g/cm3 (HWSD)      | identity (1 g/cm3 = 1 t/m3)|
| Sand / clay / silt | %         | fraction          | × 100            |
| Yield YLDG    | t/ha           | kg/ha             | ÷ 1000           |

**Critical trap**: the `.DLY` file is `(3I4,6F6.*)` fixed-width with
**no column labels**. Column order is: YEAR MON DAY SRAD TMX TMN PRCP RH WSPD.
Radiation is MJ m-2 day-1 (NOT W m-2). Temps in degC (NOT Kelvin).
Precipitation in mm (NOT kg m-2 s-1).

## Binding an observed yield product to a dag obs_shape (MANDATORY before scoring)

EPIC is a 0-D **point field** model. Most yield observations on this server are
not points -- GDHY (0.5deg gridded), SPAM, FAOSTAT and statistical yearbooks are
**area averages**. `dag.yaml` offers `outputs[YLDG].observability` BOTH
`point_time_series` and `regional_aggregate_time_series`; picking the wrong one
silently changes which metric is the verdict.

Run this BEFORE scoring anything, and record its output in the run notes:

```bash
python KISSPATH_KI_ROOT/EPIC/knowledge_infrastructure/tools/resolve_obs_shape.py \
    --var YLDG --granularity grid --geometry "0.5deg grid cell" \
    --dataset-id gdhy_v1_2_v1_3 --n-steps 20
```

Decision rule (the tool reads the contract out of `dag.yaml`, nothing hard-coded):

| obs characteristic | obs_shape | VERDICT metric (the only one) | diagnostic metrics (report, never a verdict) |
|---|---|---|---|
| station / experiment plot / single field, >=2 seasons | `point_time_series` | `pbias` | `r`, `NSE`, `KGE`, `RMSE` |
| gridded cell, region, province, nation, or a census-anchored product (GDHY, SPAM, FAOSTAT, yearbook) | `regional_aggregate_time_series` | `pbias` | `r_detr`, `r_firstdiff`, `slope_ratio`, `slope_obs`, `slope_sim`, `RMSE` |
| one season only | `point_snapshot` | `pbias` | `RMSE` |

The verdict is the dag's `determining_metric` and **nothing else**. The tool
emits `verdict_metrics` (always exactly that one metric), `diagnostic_metrics`
(pattern evidence for the chosen shape) and `non_verdict_metrics` (metrics whose
dag `metric_families` belong to a *different* obs_shape of the same var). The
detrended trend metrics are **evidence that the weather signal exists**, not a
second verdict -- `docs/validation_convention.yaml` gives
`yield / regional_aggregate_time_series` a single headline metric, `pbias`.

`dag.yaml` names metric *families* (`trend_match`), not metric *keys*
(`r_detr`). The family -> key binding lives in one data table in the tool,
`METRIC_FAMILY_SOURCE`, which records for each family **which
`ki_tools_common.metrics` scorer computes it** and which of that scorer's
emitted keys it covers (`trend_match` -> `trend_metrics`, and that includes
`PBIAS`, which `trend_metrics` returns alongside the trend keys). Verify the
binding against the live scorers before trusting a resolution:

```bash
python .../tools/resolve_obs_shape.py --self-check   # exit 0 = registry faithful
```

`--self-check` calls `all_metrics` / `trend_metrics` / `spatial_metrics` and
fails if any declared key is not actually emitted. Every `resolve()` also
carries a static version of the same check in `metric_registry_check`. A dag
family with no row in the registry is never dropped -- it is reported in
`unmapped_metric_families`, whether it came from the chosen obs_shape or from
one of the var's other shapes.

**Raw inter-annual `r` / `NSE` / `KGE` are NOT a verdict against an area-average
yield obs.** Two independent structural reasons, both verified at Changchun
(GDHY 44.25N 125.25E maize, 1997-2016, n=20):

1. *Technology trend.* The obs rises +0.163 t/ha/yr (2.66%/yr of mean; 1997-2006
   mean 5.25 -> 2007-2016 mean 6.97 t/ha). That is cultivar turnover, input
   intensification and mechanisation -- a fixed-management, fixed-cultivar,
   fixed-PPOP EPIC run has no mechanism for it (sim slope +0.003 t/ha/yr,
   slope_ratio 0.02). Raw `r` collapsed to 0.21; **detrended r = 0.38 and
   first-difference r = 0.59** -- the weather signal is there once the trend is
   removed.
2. *Variance damping.* A 0.5deg cell mean averages hundreds of heterogeneous
   fields, so its inter-annual variance is smaller than any single field's.
   Detrended sd was 0.55 t/ha (obs) vs 1.07 t/ha (sim). `NSE`/`KGE` penalise
   that scale mismatch as if it were model error.

This is exactly the dag caveat on the `regional_aggregate_time_series` block
("compare detrended trend, not inter-annual r") and `docs/validation_convention.yaml`
(`yield` / `regional_aggregate_time_series`: headline metric is `pbias` only).
See triplet **EPIC_025**.

### Yield moisture basis -- state it, never assume it

The unit table below gives only the kg/ha -> t/ha conversion. It is **not** the
whole convention: **EPIC `.ACY` YLDG/YLDF/BIOM are DRY MATTER**. The obs side's
basis is **not** something a run may assume -- but it is also no longer something
each run re-decides. `resolve_obs_shape.py` now carries an **obs moisture-basis
registry** (`OBS_MOISTURE_BASIS`), one row per obs product, each row carrying the
documentary chain that ESTABLISHES it. Ask the tool:

```bash
python tools/resolve_obs_shape.py --var YLDG --granularity grid \
    --geometry "0.5deg grid cell" --dataset-id gdhy_v1_2_v1_3 --crop maize \
    --n-steps 20            # -> .moisture_basis.obs_native / .conversion
```

**GDHY / FAOSTAT / SPAM cereals are MARKET (commercial) moisture, established**
(registered 2026-07-29, closing the open item of triplet EPIC_025):

- GDHY grid yields are *"estimated using the satellite-derived crop-specific
  vegetation index and **FAO-reported country yield statistics**"* (Iizumi &
  Sakai 2020, *Sci Data* 7:97, doi:10.1038/s41597-020-0433-7), so GDHY inherits
  FAOSTAT's reporting basis. The GDHY `.nc4` files themselves carry **no
  attributes at all** (verified: empty global attrs, unlabelled var `var`), so
  the basis cannot be read off the file — it must come from this chain.
- FAO crop-production definitions: *"Production data for cereals are reported in
  terms of clean, dry weight of grains with **12-14 percent moisture in the form
  usually marketed**"*, and *"Area and production data on cereals relate to crops
  harvested for dry grain only. Rice, however, is reported in terms of paddy."*
- => `w = 0.14` for maize in China (top of FAO's 12-14% band; also China's
  GB 1353 maize trade-moisture ceiling). `w_range = 0.12-0.14` is the
  sensitivity. The old `w = 0.155` is the **US grain-trade** convention, not
  FAO's — keep it only as a sensitivity, never as the headline.

Before scoring:

1. **Ask the registry.** A product with no row returns
   `basis: "undetermined", established: false` — then establish it from that
   product's own documentation, cite it, and **add the row** so the next run
   cannot silently re-decide.
2. Declare the basis of both sides in the run notes.
3. Convert once, either way — the PBIAS is identical:
   `sim_market = sim_dry / (1 - w)`  ==  `obs_dry = obs_market * (1 - w)`.
4. Report PBIAS on **both** bases regardless.

This is not cosmetic -- at Changchun the undeclared choice moved the dag's
*determining* metric from PBIAS **+26.8%** (dry-vs-as-published, i.e. a basis
MISMATCH) to **+50.1%** (`w=0.155`). A determining metric must never be free to
double on an undocumented per-run judgement call — which is exactly why the
basis now lives in a cited registry rather than in the agent's head.

### Known residual magnitude bias (do NOT tune it away)

After the above, EPIC still reads high against a 0.5deg cell mean. The two known
causes are (a) `OPV5` plant population still at the umstead-NC legacy 10.0
plants/m2 vs ~6.0-7.5 for NE-China rainfed spring maize, and (b) a well-managed
single HLU compared against a cell mean that averages sub-optimal fields. Per
triplet **EPIC_022**, do NOT move PPOP to shift PBIAS -- there is no gridded
plant-density product on this server, and tuning it against the scored
observation would make the verdict circular.

## Capability inventory

EPIC supports a wide range of features beyond single-crop yield. Each MUST
have a tool:

| #  | Capability                              | Tool                              |
|----|-----------------------------------------|-----------------------------------|
| 1  | Crop growth (150+ crop types in CROPCOM)| `tools/select_crop.py`            |
| 2  | Weather forcing (CMFD/NASA POWER → EPIC)| `tools/convert_forcing_to_epic.py`|
| 3  | Soil profile (HWSD → .SOL)              | `tools/build_soil_file.py`        |
| 4  | Site topography (.SIT)                  | `tools/build_site_file.py`        |
| 5  | Operations scheduling (.OPC)            | `tools/build_opc_file.py`         |
| 6  | Fertilization (FERT2012 + OPC ops)      | `tools/build_opc_file.py` (fert op)|
| 7  | Tillage (TILLCOM + OPC ops)             | `tools/build_opc_file.py` (till op)|
| 8  | Irrigation (auto or scheduled)          | `tools/configure_irrigation.py` (`.SIT` IRR + `.OPC` OPV3 — **not** EPICCONT) |
| 9  | Pesticide fate (PESTCOM + OPC ops)      | `tools/build_opc_file.py` (pest op)|
| 10 | Crop rotation (multi-year OPC)          | `tools/build_opc_file.py`         |
| 11 | Run control & list-COM files            | `tools/build_control_files.py`    |
| 12 | Execution wrapper (copy+run under Wine) | `tools/run_epic.py`               |
| 13 | Output parsing (.ACY, .ANN → CSV)       | `tools/parse_outputs.py`          |
| 14 | Water-balance validation                | `tools/parse_outputs.py` (validate)|
| 15 | Erosion / MUSLE / wind erosion outputs  | `tools/parse_outputs.py` (columns)|
| 16 | GHG (N2O, CO2, denitrification)         | `tools/parse_outputs.py` (columns)|

All tools follow validate → process → validate and import from
`ki_tools_common` where appropriate.

## Tool reference (short)

| Tool                         | Purpose                                         |
|------------------------------|-------------------------------------------------|
| `convert_forcing_to_epic.py` | CMFD/NASA POWER → .DLY/.WP1/.WND                |
| `build_site_file.py`         | copy umstead.SIT + overwrite lat/lon/elev/slope |
| `build_soil_file.py`         | copy umstead.SOL + overlay HWSD layer props    |
| `build_opc_file.py`          | copy umstead.OPC + rewrite plant/fert/harvest   |
| `select_crop.py`             | browse CROPCOM.DAT → crop code                  |
| `configure_irrigation.py`    | set `.SIT` IRR method + `.OPC` OPV3 auto trigger |
| `build_control_files.py`     | stage templates + rewrite EPICRUN.DAT           |
| `run_epic.py`                | copy-first Wine execution wrapper               |
| `parse_outputs.py`           | parse .ANN/.ACY → CSV + water balance check     |
| `quickstart.py`              | **one-command whole pipeline** from lat/lon/crop/years |
| `configure_control.py`       | edit EPICCONT.DAT simulation-control flags      |
| `edit_opc.py`                | low-level .OPC row editor (add/replace single ops) |
| `set_output_types.py`        | choose which daily/annual output files EPIC writes |
| `tune_parm.py`               | edit PARM1102.DAT global model parameters       |

### Start here for a NEW site: `quickstart.py`

`quickstart.py` chains every stage below (crop calendar → NPKGRIDS fertiliser
→ SPAM yield target → .SIT/.SOL/.OPC → forcing → control files → Wine run →
parse) from nothing but lat/lon/crop/years. Use it instead of driving the nine
stage tools by hand:

```bash
cd KISSPATH_KI_ROOT/EPIC/knowledge_infrastructure/tools
python3 quickstart.py --lat 44.25 --lon 125.25 --crop corn \
        --start 1995 --end 2016 --source cmfd --irrigation dryland
```

Forcing extraction from the CMFD 3-hourly store costs **~80 s per simulated
year** at one point (7 variables × 12 monthly NetCDFs). `convert_forcing_to_epic.py`
memoises each year under `<workspace>/.forcing_cache`, so a re-run or a resumed
detached run skips years already extracted (override the location with
`$EPIC_FORCING_CACHE`). A multi-decade setup should therefore be launched
detached, not inline.

**CMFD store**: point the forcing at `Data_forcing_03hr_010deg` (3-hourly), NOT
`Data_forcing_01dy_010deg`. The daily store carries only a daily MEAN
temperature, so `TMX == TMN` reaches EPIC as a zero diurnal range — no error,
just wrong heat units and PET (triplet EPIC_023). `convert_forcing_to_epic.py`
now resolves the 3-hourly store (hc_ssd first, disk1 fallback) and raises if a
degenerate diurnal range is detected.

### Crop maturity — set PHU from the SITE, never from the template

`quickstart.py` now does this for you: it builds the forcing BEFORE the `.OPC`
and passes `phu=compute_phu(...)` plus the `n_cap` of triplet EPIC_018. Drive
the stage tools by hand only if you need to override those.

The PLANT operation's `OPV1` is the crop's **PHU** (Potential Heat Units) and
EPIC reports `HUSC = accumulated HU / PHU` on every operation line of the
`.OUT` log. `dag.yaml` requires **HUSC 0.9–1.2 at harvest** or the yields are
suspect. The shipped umstead value (1550, North Carolina) is wrong at most
sites, so derive PHU from the run's own weather **after** the forcing stage:

```python
from build_opc_file import build as build_opc, compute_phu, crop_base_temp
phu = compute_phu(f"{ws}/STN01.DLY", "05-04", "09-13", crop_base_temp("CORN"))
build_opc(name, "CORN", "05-04", "09-13", "09-13", "05-04", n, ws, phu=phu)
```

Check it afterwards: `grep -E "YLD=.*HUSC=" <run>.OUT`. See triplet EPIC_021.

### MANDATORY post-run check — the heat-unit index must reset every year

A multi-year rotation only behaves if EPIC **terminates** the crop at the end
of each season. Two greps, always, before you trust a yield series:

```bash
grep " HUI " <run>.OUT | head          # January column MUST be 0.00 every year
grep "CSP2WD" <run>.OUT                # HUSC at harvest must be 0.9-1.2
```

If January HUI drifts up year on year (`0.00, 0.11, 0.21, 0.29 …`) the crop is
never being killed and its heat units carry across the rotation boundary, so
HUSC at harvest reads `1 + residual` and yields are inflated. The cause is a
`.OPC` KILL row (equip 451) written with **crop_id = 0** instead of the crop's
CROPCOM code — the shipped `templates/umstead.OPC` kill row carries `2` (CORN).
`build_opc_file.py` had this bug and now writes `crop_code`; see triplet
EPIC_024. The failure is completely silent: EPIC runs, the `.ACY` looks
plausible, and the over-shoot masquerades as a PHU error — which invites the
wrong "raise the PHU" fix.

### Irrigation is TWO fields in TWO files — and neither is EPICCONT.DAT

An "irrigated" run that leaves `.ACY IRGA = 0.000` in every year is still a
DRYLAND run. EPIC's switch is:

| field | file | meaning |
|---|---|---|
| `IRR` | first integer of the flag line at the end of `<run>.SIT` | 0 dryland, 1 sprinkler, 2 furrow, 3 irrigation-with-fert, 4 automatic big-gun/lagoon, 5 drip (codes read off the `.OUT` MANAGEMENT DATA echo) |
| `OPV3` | the PLANTING row of `<run>.OPC` | automatic-irrigation trigger (plant water-stress factor, e.g. 0.85); **0 means "wait for scheduled ops"** |

`configure_irrigation.py` sets both, and `quickstart.py --irrigation furrow
--irrigation-trigger 0.85` forwards them. It must run AFTER `build_opc_file`,
which rewrites the `.OPC`. Verify every irrigated run:

```bash
grep -E "DRYLAND AGRICULTURE|IRRIGATION" <run>.OUT   # method echo
awk 'NR>11{print $1, $4, $16}' <run>.ACY             # YR YLDG IRGA
```

Until 2026-08-10 the tool wrote the flag into `EPICCONT.DAT` row 2, which holds
no irrigation field at all (verified by sweeping all 21 of its integers through
the binary), so **every irrigated run this KI ever produced was dryland** —
triplet **EPIC_032**, which supersedes item 3 of EPIC_019. EPIC_019's "at a
monsoon site irrigation cannot help" still holds *for monsoon sites*: check the
`.ACY WS` column first. At Po Valley (45.25N 9.75E) WS is 25-35 stress days and
furrow irrigation moves 1984 maize from 7.70 to 10.25 t/ha dry (IRGA 200 mm).

### Non-China sites: terrain and forcing

- `_lookup_terrain` resolves elevation/slope from the China DEM, then the
  **global MERIT DEM** (`KISSPATH_DATA/MERIT_DEM`, 5°×5° tiles). Before
  2026-08-10 the MERIT step did not exist and every non-China `.SIT` silently
  carried 100 m / 1% slope (triplet **EPIC_031**).
- `--source nasa_power` is the practical global forcing (~3 s/simulated year vs
  2-6 min for CMFD 3-hourly and >6 min for MSWX). Its **radiation record starts
  1984-01-01** (temperature/precipitation start 1981), so a GDHY comparison
  forced by NASA POWER is a 1984-2016 window (triplet **EPIC_030**).
- The per-year forcing memo used to drop every numpy-array variable, which
  killed the whole NASA POWER path silently; delete a `.forcing_cache` written
  before 2026-08-10 (triplet **EPIC_029**).

### Plant population (OPV5) is a site decision, not a default

`build_opc_file.build(..., ppop=)` sets the plant row's OPV5 (plants m-2,
echoed as the `.ACY` PPOP column). The default 10.0 is the umstead
North-Carolina legacy — the same site-blind class of value as `phu=1550` — and
it drives LAI, biomass and yield. Real densities are typically 6.0-7.5
plants m-2 for NE-China rainfed spring maize. No gridded planting-density
product exists on this server, so pass a sourced value when you have one;
never tune it against the observation you are scoring.

`quickstart.py` now forwards it too — `--ppop` / `quickstart(..., ppop=)`.
Before that it had no such parameter at all, so **every** quickstart run
silently inherited 10.0 plants m-2 (100,000 plants/ha) no matter what this
section said — a documented requirement with no way to satisfy it from the
recommended entry point. Omit the flag to keep the documented default; pass it
ONLY with a recorded source. Published NE-China spring-maize density treatments
sit at 30,000 / 52,500 / 75,000 / 97,500 plants ha-1 with an optimum near
76,000 plants ha-1, so 100,000 plants ha-1 is above every published treatment —
but the *average farmer density for a given cell-year* is not established on
this server, and any pick inside that range moves PBIAS a lot. Until a source
pins it, report a `--ppop` run as a labelled **sensitivity**, never as the
verdict (triplet EPIC_022).

### EPIC binary location

The executable is resolved by `tools/_common.resolve_binary()`, in order:
`$EPIC_BINARY` → `models/EPIC/bin/epic1102-official_release.exe` (the durable
install) → `models/EPIC/source/repo/` → the legacy `_work_v2` dissection
scratch path. Do not hard-code the scratch path — it is transient.

## Quick validation (fastest path — use this for KI testing)

```bash
cd KISSPATH_KI_ROOT/EPIC/knowledge_infrastructure
python3 quick_validate.py          # uses existing umstead outputs
python3 quick_validate.py --rerun  # force a fresh Wine execution
```

This runs the shipped umstead example (NC corn, 1930-1944, 15 years),
parses `.ANN` and `.ACY` outputs, checks water balance and yield ranges,
and prints JSON in the KI test format. Takes ~5 seconds with existing
outputs or ~30 seconds with `--rerun`.

## Quick-start example (reproducing shipped umstead run)

```bash
# copy the shipped template workspace somewhere writable, then:
cp KISSPATH_KI_ROOT/EPIC/bin/epic1102-official_release.exe .
wine ./epic1102-official_release.exe
ls umstead_0.*        # .OUT .ACY .ANN .DGN .DCN ...
```

(The old `_work_v2/EPIC/epic_workspace` path in earlier revisions of this file
is a transient dissection scratch dir and no longer exists.)

## Water balance sanity check

After every run, parse `<name>_0.ANN` and confirm:

    P (mm/yr) = ET (mm/yr) + Q (mm/yr) + ΔS

Note: Q in the `.ANN` file is **surface runoff only**. Deep percolation and
lateral subsurface flow are not included, so the residual P − ET − Q is
typically 200–600 mm/yr for humid sites. This is normal. An error is
indicated when ET exceeds P + IRGA (energy violation) or when values
are negative or zero.

## Reference KIs

- `KISSPATH_KI_ROOT/GLM/knowledge_infrastructure/` —
  similar "closed-binary + fixed-format input" pattern
- Data KIs (unit verification):
  (dataset KI dir names are UPPER-CASE on disk; the lower-case paths in
  earlier revisions of this file do not resolve)
  - `KISSPATH_DATA_KI/CMFD/SKILL.md`
  - `KISSPATH_DATA_KI/NASA_POWER/SKILL.md`
  - `KISSPATH_DATA_KI/HWSD/SKILL.md`

  Forcing/soil/terrain LOADERS live in `ki_tools_common`
  (`load_forcing`, `soil_utils`, `terrain`), not under `data_ki/*/tools/`.

## Validation tier

This KI has been validated at **tier = analytic**: the shipped
`umstead` example (corn, NC, 1930-1944, 15 years) is run unmodified
through the binary, annual `*.ANN` is parsed, and a water-balance check
is applied. Independent observed yield/ET/discharge comparisons would
upgrade this to `real` tier.

## Files in this KI

```
SKILL.md                            # this file
knowledge_infrastructure.yaml       # machine-readable index
preflight_check.py                  # environment check
quick_validate.py                   # one-command KI validation
templates/                          # shipped example workspace (copy-first!)
tools/                              # 9 copy-first Python tools
docs/                               # 7 stage guides
diagnostics/triplets.yaml           # 17 symptom/diagnosis/remedy entries
```
