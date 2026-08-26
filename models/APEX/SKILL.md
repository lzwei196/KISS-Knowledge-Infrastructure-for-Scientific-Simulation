---
name: apex
description: >-
  APEX (Agricultural Policy/Environmental eXtender); Theoretical Documentation v0604 (BREC
  #2008-17, 2008) science lineage, run as the v0806 user-guide…. Covers Whole-farm /
  small-watershed agronomy, hydrology, water quality at daily step; Hydrology: rainfall
  interception, surface runoff (SCS Curve Number or Green-Ampt), peak rate…. Use when the
  task involves running, configuring, calibrating or interpreting APEX.
---

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
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong (model crashes, wrong output,
> unexpected values), follow this order. Do NOT skip steps or write debug scripts:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Check the XLSM editor** — `reference/apexeditorrev2203.xlsm` contains the
>    EXACT format specification for every APEX input file (APEXCONT.DAT, OPC, SOL,
>    SIT, list files). Open with `openpyxl` to read column names, parameter IDs,
>    and valid ranges. Also see `reference/apex_formats.json` for pre-extracted specs.
> 3. **Read official docs / Find working examples** — Look in the example workspace
>    for the validated working case. Compare your inputs against these.
> 4. **Fix the tool** — Now that you know what "correct" looks like, make targeted fixes
>
> **XLSM Editor Reference** (`reference/apexeditorrev2203.xlsm`):
> The official APEX parameter editor contains complete format specs for ALL input files.
> Key sheets: APEXCONT.DAT (86 control params), MNGT.MNG (operations format),
> SOIL.SOL, SITE.SIT, APEXPLANT.TAB (crop database), APEXTILL.TAB (tillage),
> APEXFERT.TAB (fertilizers), all list files. Use `reference/apex_formats.json`
> for the pre-extracted machine-readable version.
>
> **OPC Management File Format** (from XLSM):
> Col 1: YEAR, Col 2: MONTH, Col 3: DAY, Col 4: TILLAGE_ID (from TILLTABLE),
> Col 5: MACHINE_ID, **Col 6: PLANT_ID** (from CROPCOM.DAT), Col 7: OPV,
> Col 8: OPV1, Col 9: OPV2. To change crop: modify **column 6**, NOT column 4.

---

# APEX v0806 (Agricultural Policy / Environmental eXtender) — Knowledge Infrastructure

**Model**: APEX v0806 (PE32 Windows binary via Wine)
**Distributor**: Texas A&M AgriLife / Blackland Research and Extension Center
**Source**: https://epicapex.tamu.edu/software/
**Language**: Fortran 90 (Intel Fortran compiled, PE32 executable)
**Domain**: Field- and watershed-scale agronomy / hydrology / water-quality
**Validation status**: `validated` — Bengbu China corn 6.21 t/ha vs 5.6 observed (+11% bias).
Multi-subarea farm (4 fields) validated with CMFD weather, HWSD soil, GGCMI calendar.

**CRITICAL: Use v0806, NOT v1501.** The v1501 binary has a confirmed issue where annual
crops produce zero biomass (BIOM=0.01) due to P cycling NaN in the Century C/N model.
Exhaustively tested with 25 PARM fixes, soil P initialization 3-50 ppm, Century pool
initialization from OC — still zero yield. v0806 produces 4.46-6.21 t/ha corn.
Template: Riesel TX cropland (ex1_RiselTX), NOT WRE pasture.
Binary: `reference/APEX0806.exe` (run via `wine APEX0806.exe`).

---

## Overview

APEX (Agricultural Policy / Environmental eXtender) is the multi-subarea, watershed-
scale extension of the EPIC field-scale model. It simulates the full agronomic,
hydrologic, erosion, nutrient, pesticide, carbon, grazing-livestock, and economic
processes of fields, farms, and small watersheds at a daily time step, optionally
with sub-daily routing.

**What APEX does** (one paragraph per major process):

- **Hydrology** — Curve Number (NRCS CN) or Green-Ampt infiltration; soil-water
  routing through up to 30 layers; ET via Penman-Monteith / Penman / Priestley-
  Taylor / Hargreaves / Baier-Robertson (selectable); snow melt; lateral subsurface
  flow; groundwater return flow; tile drainage.
- **Erosion** — Six water-erosion equations (USLE, MUSLE, MUST, MUSS, MUSI, RUSLE,
  RUSLE2) and the WEQ wind-erosion model.
- **Nutrient cycling** — N (mineralization, nitrification, denitrification, fixation,
  volatilization, leaching, runoff and sediment loss) and P (Sharpley adsorption-
  desorption with labile/active/stable pools) cycles. Optional Century carbon model.
- **Crop growth** — EPIC-style heat-unit phenology with LAI, biomass, root growth,
  water/nutrient/temperature/aeration stresses, harvest index. ~120 crops in
  PLANTABLE.DAT/CROPCOM.DAT.
- **Management** — Rotations, tillage, fertilization, irrigation (auto or scheduled),
  pesticides, grazing, manure, drainage, terraces, contouring, strip cropping,
  liming, harvesting, residue, cover crops, fire, controlled burn.
- **Routing** — APEX subareas drain to one another via channel/floodplain routing
  (variable-storage or Muskingum). Sediment, nutrients, pesticides routed.
- **Economics** — Crop budgets, costs/returns by operation.

**Key difference from EPIC** — APEX adds the multi-subarea routing topology (each
`*.SUB` file describes one subarea; `SUBA****.DAT` lists them; routing direction is
encoded by `WSA / CHL / RCHL`). EPIC is single-field; APEX is watershed.

---

## Installation

### Protected runtime assets

This KI runs `reference/APEX0806.exe` through Wine and starts from the
`examples/ex1_RiselTX/` reference template. These files may be installed in
GeoForge's shared APEX workspace because they cannot be redistributed in the
public app bundle. GeoForge automatically carries already installed assets
into each session KI working copy. Do not ask the user to copy or download them
again when the shared APEX installation has already been verified.

APEX0806 **always** opens inputs from the **current working directory** and
writes outputs there. `s1_setup_workspace.py` creates a project-local run
workspace by copying the Riesel template and executable; `s6_run_apex.py` then
invokes that copy with Wine.

### Validation that the binary works

```bash
# Run preflight (verifies v0806, Wine, the Riesel template, and a real run)
python preflight_check.py
```

Expected output:
```
[OK] APEX0806 binary found at .../reference/APEX0806.exe
[OK] Wine runtime found at .../wine
[OK] Riesel reference template found at .../examples/ex1_RiselTX
[OK] Real APEX0806 Riesel run completed with fresh output
[OK] preflight passed — APEX0806 is installed and runnable
```

---

## File ecosystem (FORTRAN FIXED-WIDTH FORMATS — COPY, DON'T GENERATE)

APEX v0806 is a Fortran-90 model. **Every input file is a Fortran fixed-format
text file with rigid column positions**. The single most important rule:

> **NEVER WRITE APEX INPUT FILES FROM SCRATCH. ALWAYS COPY FROM
> `examples/` AND MODIFY SPECIFIC VALUES IN PLACE.**

The installed KI uses the validated cropland reference dataset in
`examples/ex1_RiselTX/`. Every tool in `tools/` follows the
copy-template-then-modify pattern.

### Control / list files (fixed names, single watershed)

| File | Purpose | Fortran unit |
|------|---------|--------------|
| `APEXFILE.DAT`  | Master file index — 19 lines, each `<token> <filename>` | 22 |
| `APEXRUN.DAT`   | Run table — one line per run referencing site/subarea/operation IDs | 24 |
| `APEXCONT.DAT`  | Run control — NBYR, IYR, IMO, IDA, IPD, NGN, IGN; CO2; physics options | 30 |
| `APEXDIM.DAT`   | Array dimensions (max subareas, layers, owners, etc.) | 36 |
| `SITELIST.DAT`  | Numbered list of `*.SIT` files (referenced by ISIT in APEXRUN.DAT) | 12 |
| `SUBSLIST.DAT`  | Numbered list of `*.SUB` files (referenced by ISUB) | 14 |
| `SOILLIST.DAT`  | Numbered list of `*.SOL` files (referenced by INPS in `*.SUB`) | 17 |
| `MNGTLIST.DAT`  | Numbered list of operation schedule `*.OPC`/`*.MGT` files | 18 |
| `WPM1LIST.DAT`  | Weather parameter (monthly statistics) station list | 13 |
| `WINDLIST.DAT`  | Wind parameter station list | 13 |
| `WDLYLIST.DAT`  | Daily weather (`*.DLY`) station list | 13 |
| `PSOLIST.DAT`   | Point source list | 19 |

### Per-subarea files (one set per subarea)

| File | Purpose | Format spec |
|------|---------|-------------|
| `*.SIT` | Site (lat/lon, elevation, CO2, weather station references) | 9 lines, fixed-width 8-col fields, Manual §2.3 |
| `*.SUB` | Subarea (soil ID, operation ID, hydrologic + routing params, grazing herd) | 12 lines + padding rows of zeros to 22 lines (apex1501 EOF quirk), Manual §2.5 |
| `*.SOL` | Soil profile (up to 30 layers × 50+ properties) | Manual §2.7 |
| `*.OPC` / `*.MGT` | Operation schedule (planting, fert, harvest, tillage rows) | Manual §2.10 |
| `*.WP1` | Monthly weather statistics (12 months × 13 variables) | Manual §2.13 |
| `*.WND` | Monthly wind statistics | Manual §2.14 |
| `*.DLY` | Daily measured weather (year, month, day, srad, tmax, tmin, prcp, RHM, wind) | Manual §2.15 |

### Parameter / table files (shared globally, ship with model)

`PLANTABLE.DAT` (or `CROPCOM.DAT`) — crop parameters (~120 crops)
`TILLTABLE.DAT` (or `TILLCOM.DAT`) — tillage implements
`PESTTABLE.DAT` (or `PESTCOM.DAT`) — pesticides
`FERTTABLE.DAT` (or `FERT2012.DAT`) — fertilizers
`HERDTABLE.DAT` (or `HERD.DAT`) — livestock herd parameters
`APEXPARM.DAT` (or `PARM1102.DAT`) — APEX general/internal parameters
`APEXPRNT.DAT` (or `PRNT1102.DAT`) — output print code selections
`MLRNCOM.DAT` — measured weather table (for MLRN feature)
`TR55COM.DAT` — TR-55 SCS rainfall distribution constants

---

## Pipeline stages (KI tools)

Stage | Tool | Purpose
--- | --- | ---
**S1** | `tools/s1_setup_workspace.py`     | Copy entire example template to a fresh workspace dir
**S2** | `tools/s2_convert_forcing.py`     | Pull global daily forcing (CMFD/MSWX/NASA POWER) → write `*.DLY`, `*.WP1`, `*.WND`
**S3** | `tools/s3_build_soil.py`          | HWSD → `*.SOL` (10 layers, 50+ properties) using ROSETTA van Genuchten params
**S4** | `tools/s4_update_site.py`         | Edit `*.SIT` lat/lon/elevation in place
**S5** | `tools/s5_update_control.py`      | Edit `APEXCONT.DAT` simulation period & physics options
**S6** | `tools/s6_run_apex.py`            | Run binary inside workspace; collect outputs; check water balance
**S7** | `tools/s7_parse_output.py`        | Parse `*.OUT` annual + `*.SAD` daily subarea → CSV

Every tool follows **validate → process → validate**:
- `validate_inputs()` checks lat/lon ranges, year ranges, file existence
- Process step copies template, modifies via string replacement (NOT regeneration)
- `validate_outputs()` checks the resulting file is parseable and physically plausible

---

## Unit trap table

| Variable | APEX unit | Common other units (DON'T mix up) | Where it appears |
|---|---|---|---|
| Latitude / longitude | decimal degrees | DMS, radians | `*.SIT` line 4 fields 1–2 |
| Elevation | **m** | ft (US Survey), km | `*.SIT` line 4 field 3 |
| Channel length CHL / RCHL | **km** | m, mi | `*.SUB` line 4 fields 2–3 |
| Channel slope CHS | **m/m** (dimensionless fraction) | %, deg | `*.SUB` line 4 field 5 |
| Watershed area WSA | **ha** | m², km², ac | `*.SUB` line 4 field 1 |
| Daily precipitation | **mm/day** | inches, cm | `*.DLY` field 6 |
| Tmax / Tmin | **°C** | °F, K | `*.DLY` fields 4–5 |
| Solar radiation SRAD | **MJ/m²/day** | W/m², ly/day | `*.DLY` field 3 |
| Wind speed | **m/s** | mph, km/h | `*.DLY` field 8 (if NGN includes wind) |
| Relative humidity | **fraction (0–1)** | percent | `*.DLY` field 7 |
| CO2 | **ppm** (volume) | ppmv, mol/mol | `APEXCONT.DAT` line 3 field 2; `*.SIT` line 4 field 5 |
| Saturated K (Ksat) | **mm/h** | cm/day, m/s | `*.SOL` |
| Soil bulk density | **g/cm³** (= Mg/m³) | kg/m³ | `*.SOL` |
| Soil organic C | **% by weight** | g/kg, kg/ha | `*.SOL` |
| Soil pH | **dimensionless** | — | `*.SOL` |
| N applied | **kg/ha** | lb/ac | `*.OPC` fertilizer rows |
| Crop yield (output) | **t/ha** dry matter | bu/ac, kg/ha | `*.ACY`, `*.OUT` |
| Water yield WYLD | **mm** (or m³ in mass balance block) | inches | `*.OUT` |
| Sediment yield Y | **t/ha** | t/ac, kg/ha | `*.OUT` |

**Most common unit traps** (causing silent wrong answers):
1. **Slope as percent vs m/m** — APEX wants 0.05 for 5%, NOT 5.0.
2. **Elevation in feet** — APEX uses meters universally. Convert ft × 0.3048.
3. **CO2 in ppmv vs ppm** — APEX uses ppm by volume; modern atmospheric value ≈ 420 ppm.
4. **Daily SRAD in W/m² instead of MJ/m²/day** — multiply W/m² by 0.0864 to get
   MJ/m²/day (mean daytime W/m² × seconds per day / 1e6 ≈ × 0.0864 for daily mean).
5. **Lat in southern hemisphere positive** — APEX wants negative degrees south.

---

## Quickstart — run APEX on the bundled example

```bash
cd KISSPATH_KI_ROOT/APEX/knowledge_infrastructure
python preflight_check.py
python tools/s6_run_apex.py --workspace /tmp/apex_run --use-example
python tools/s7_parse_output.py --workspace /tmp/apex_run --out /tmp/apex_run/results.csv
```

Expected output: 15-year simulation (1979–1993) of a 1.63 ha pasture subarea in
Marena OK; annual water yield ≈ 584 mm/yr; ET ≈ 348 mm/yr (1979–93 mean).

---

## Quickstart — run APEX on a new lat/lon

```python
from tools.s1_setup_workspace import setup
from tools.s2_convert_forcing  import build_forcing
from tools.s3_build_soil       import build_soil
from tools.s4_update_site      import update_site
from tools.s5_update_control   import update_control
from tools.s6_run_apex         import run
from tools.s7_parse_output     import parse

ws = setup("/tmp/apex_bengbu")                                   # copy template
build_forcing(ws, lat=32.94, lon=117.36, year1=2010, year2=2015) # CMFD → DLY+WP1+WND
build_soil(ws,    lat=32.94, lon=117.36)                         # HWSD → SOL
update_site(ws,   lat=32.94, lon=117.36, elev_m=23.0)
# spinup_years=25 prepends 25 extra years (soil equilibration). ngn=2 = generate
# TMAX from WP1 monthly stats, read all other variables from DLY.
update_control(ws, year1=2010, year2=2015, ngn=2, spinup_years=25)
run(ws)                                                           # wine APEX0806.exe
df = parse(ws)                                                    # → DataFrame; spinup rows marked
df_actual = df[~df["spinup"]]                                    # filter to analysis period
```

**Important**: also copy a validated OPC file to the workspace (or generate one
with s9_generate_crop_opc.py) and update OPSCCOM.DAT to point subareas at it.
s9 generates APEX0806-compatible op codes (136/261/292) and fertilizer codes (53/54).
Do NOT use OPC files from APEX1501 runs — the op codes are different.

---

## Output files (key ones — tools/s7 parses these)

| File | What it contains |
|------|------------------|
| `<run>.OUT` | Master annual print (per subarea, per year) — most important |
| `<run>.SAD` | Daily subarea output (when IPD specifies daily) |
| `<run>.SUS` | Subarea summary |
| `<run>.ACY` | Annual crop yield |
| `<run>.MAN` | Watershed manure summary |
| `<run>.MSW` | Monthly subarea water |
| `<run>.DPS` | Daily pesticide |
| `<run>.AWP` | Annual watershed pesticide |
| `<run>.HYC` | Hydrograph at watershed outlet |
| `RUN1501.SUM` | Multi-run summary (one row per APEXRUN.DAT entry) |
| `EPICERR.DAT` | Error log (check this if a run crashes) |

Annual `*.OUT` rows that matter for water balance verification:
- **PCP** (precipitation, m³ for whole watershed)
- **WYLD** (water yield)
- **ET** (evapotranspiration)
- **DPRK** (deep percolation)
- **PER** (percolation)
- **DF** (delta storage)

Closure: `PCP ≈ WYLD + ET + DPRK + ΔS` (within ±5%).

---

## APEX0806 vs APEX1501 — critical differences

The KI uses **APEX0806** (PE32 Windows binary via Wine). APEX1501 is a native Linux
binary but has a confirmed P-cycling NaN bug that produces zero biomass for annual
crops. Never use apex1501 for crop yield work.

### Operation codes (DIFFERENT between versions — mixing them silently misfires)

| Action | APEX0806 code | APEX1501 code |
|--------|:---:|:---:|
| Plant / drill | **136** | 132 |
| Fertilize | **261** | 580 |
| Harvest grain | **292** | 316 |
| Field cultivator | 151 | 151 (same) |
| Cultivation | 157 | 157 (same) |
| Kill crop | 451 | 397 |

### Fertilizer codes (APEX0806 FERTCOM.DAT only has entries 1–72)

| Nutrient | Safe code | Name | Notes |
|----------|:---------:|------|-------|
| Nitrogen | **53** | Elem-N, 100%N | Use this, not 92 |
| Phosphorus | **54** | Elem-P, 100%P | Use this, not 93 |

**Fert codes 92/93 do NOT exist in APEX0806's FERTCOM.DAT.** They trigger a
Fortran `PAUSE` that blocks the process indefinitely when running via Wine
without a tty (see triplet `fert_code_pause`).

### File ecosystem differences

APEX0806 uses **COM-style list files** (CRLF required):

| APEX0806 file | APEX1501 equivalent | Purpose |
|---|---|---|
| `WDLSTCOM.DAT` | `WDLYLIST.DAT` | Daily weather station list |
| `WPM1.DAT` | `WPM1LIST.DAT` | Monthly weather parameter list |
| `WINDCOM.DAT` | `WINDLIST.DAT` | Wind parameter list |
| `SITECOM.DAT` | `SITELIST.DAT` | Site list |
| `SOILCOM.DAT` | `SOILLIST.DAT` | Soil list |
| `OPSCCOM.DAT` | `MNGTLIST.DAT` | Operation schedule list |
| `SUBACOM.DAT` | `SUBSLIST.DAT` | Subarea list |

COM-style list files require **CRLF** (`\r\n`) line endings. APEXCONT.DAT and
OPC files use LF. Writing COM files with LF-only causes silent misreads.

### Wine execution — CONOUT$ trap

APEX0806 writes status messages to the Windows console handle `CONOUT$`. When
running under Wine without a controlling tty (nohup, background `&`, systemd),
Fortran `WRITE(*,...)` fails with:

```
forrtl: severe (38): error during write, unit -1, file CONOUT$
```

**Fix**: always invoke via Python subprocess with `capture_output=True` (s6 already
does this). Never launch with `nohup wine APEX0806.exe &` directly from the shell.

### Spin-up requirement

The ex1_RiselTX template has Texas soil at Texas-climate equilibrium. For any
non-Texas location, a **minimum 20–25 year spin-up** is required before the soil
water/nutrient pools reach steady state for the new climate. Without spin-up:
WS > 50, yields < 2 t/ha for the first several years regardless of management.

s5_update_control.py handles this via `--spinup-years N` (default 25). The forcing
dataset is recycled over the spin-up years. s7_parse_output.py marks spin-up rows
with `spinup=True` for easy filtering.

---

## Known traps & quirks (from the 1501 binary specifically)

1. **Filenames are case-sensitive on Linux** — APEX1501 reads filenames literally
   from `APEXFILE.DAT` and other list files. If `SITELIST.DAT` says `SITE01.SIT`
   but the actual file is `SITE01.sit`, you get a `File ... IS MISSING` error and
   silent exit 0. Always use **uppercase** extensions on disk.
2. **`APEXFILE.DAT` requires the `LWE.DAT` line** — if you take a dataset from a
   pre-1501 build, you must append a `FLWE LWE.DAT` line and create an empty
   `LWE.DAT` file (or the binary EOFs at unit 22).
3. **Subarea `*.SUB` files need ≥22 lines for apex1501** — the manual documents 12
   lines per subarea, but apex1501 reads beyond and EOFs at MAIN_1501.f90:2858.
   Pad with rows of `0.00` until the file has 22 lines.
4. **`APEXCONT.DAT` is structured** — apex1501 expects ≥6 lines plus a long block
   of zero rows (the EPIC-derived padding pattern). Use the example template.
5. **Negative WSA in `*.SUB`** signals "this subarea's runoff is added to another
   subarea before routing further downstream" — easy to set wrong.
6. **CHL == RCHL** identifies a headwater (extreme) subarea. CHL > RCHL identifies
   a downstream subarea. Setting CHL < RCHL is invalid.
7. **`AYEAR.DAT`** must contain the simulation start year as a single integer line —
   if missing, weather generator will silently spin its own random sequence.
8. **`EPICERR.DAT`** — the error log file. Always check this after a crash; it
   often holds the real diagnostic message that the stderr `forrtl: severe (...)`
   doesn't reveal.
9. **Statically linked** — no `LD_LIBRARY_PATH`, no patchelf needed; runs on
   any Linux x86-64 from kernel 3.2+.
10. **Exit code is always 0 even on Fortran severe errors** — never trust the exit
    code; always check whether `RUN1501.SUM` was written and whether `*.OUT`
    contains the closing `TOTAL RUN TIME` line.

---

## Scoring YLDG (or BIOM) against a gridded / regional-aggregate yield (GDHY, SPAM, FAOSTAT)

When the obs is a **GDHY 0.5-degree cell** (~2500 km2 cropland area-average), a
SPAM pixel/region, or a national FAOSTAT series, it is a
`regional_aggregate_time_series`, **NOT** a `point_time_series`. A GDHY cell is an
area-average over an entire 0.5-deg of mixed cropland, not a field trial. Two
MANDATORY setup rules (dag.yaml `outputs[YLDG].observability`, lines 146-151):

1. **Classify as an aggregate and DETREND before scoring variability.**
   Set `obs_shape=regional_aggregate_time_series`,
   `comparison_mode=aggregate_trend_comparison`. Regional/gridded yields carry a
   technology/management **trend** (e.g. the Bengbu 32.75N,117.25E GDHY cell rises
   ~3.0 -> 4.7 t/ha over 1981-2016) that a fixed-management, weather-driven APEX
   run structurally CANNOT reproduce. Before comparing inter-annual variability,
   apply a `detrending_option` (`linear_residual` or `first_difference`) to BOTH
   sim and obs and compute r on the residuals; report level `pbias` for magnitude
   AND detrended `r` for pattern. NEVER score the raw levels of a trended aggregate
   as `point_time_series` -- that yields spuriously catastrophic scores (this case:
   nse -20.5, r 0.06 against a trend the model was never expected to track).

2. **Management must be CELL-AVERAGE representative, not field-optimal.**
   A single high-input subarea (PHU1800, N=184.8 kg/ha at full potential) yields
   the field-trial optimum ~6.7 t/ha -- nearly 2x the GDHY cell average of ~3.4 t/ha
   (this case: pbias +96%). Disabling auto-irrigation ALONE is insufficient. For a
   0.5-deg area-average, configure management representative of the actual regional
   cropping: reduce N toward the regional mean application rate, use the regional
   cultivar/PHU, keep the dominant water regime (rainfed/supplemental for the Huai
   plain), and/or apply an area-weighted marginal-land fraction, so the simulated
   MEAN targets the GDHY cell mean (~3.4 t/ha) rather than the field-trial validation
   target (5.6-6.2 t/ha). This is a *representativeness* setup choice (dag `scope_in`:
   management/fertilization/irrigation), NOT parameter calibration.

---

## References

- APEX1501 User Manual (November 2023), Steglich et al., Texas A&M AgriLife
  https://epicapex.tamu.edu/media/pkff4m34/the-apex1501-user-manual-november-2023.pdf
- APEX1501 Theoretical Documentation (January 2023), Williams et al.
  https://epicapex.tamu.edu/media/2mwdlhte/the-apex1501-theoretical-documentation-january-2023.pdf
- Williams, J. R., et al. (2008). The APEX model. In Watershed Models. CRC Press.
- pyAPEXSCU (Maskey et al.) — published worked example used as our test dataset
  https://github.com/mlmaskey/pyAPEXSCU
