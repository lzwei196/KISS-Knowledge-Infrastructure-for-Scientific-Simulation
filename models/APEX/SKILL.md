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

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (10 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (9 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (24 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (16 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |
| what past runs learned | `.kdt_evolution.jsonl` | append-only memory of previous runs and fixes on this KI. |

*Projected 2026-08-17 from the KI's actual contents — 10 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/quickstart.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/quickstart.py --help` |
| `tools/s1_setup_workspace.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_setup_workspace.py --help` |
| `tools/s2_convert_forcing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_convert_forcing.py --help` |
| `tools/s3_build_soil.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_build_soil.py --help` |
| `tools/s4_update_site.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_update_site.py --help` |
| `tools/s5_update_control.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_update_control.py --help` |
| `tools/s6_run_apex.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_run_apex.py --help` |
| `tools/s7_parse_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_parse_output.py --help` |
| `tools/s8_update_operations.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_update_operations.py --help` |
| `tools/s9_generate_crop_opc.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s9_generate_crop_opc.py --help` |

*10 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

# APEX 1501 (Agricultural Policy / Environmental eXtender) — Knowledge Infrastructure

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

### Binary (already installed)

```
APEX 1501 binary:  KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent/_work_v2/APEX/source/repo/Apex 1501 - Linux/apex1501
Version:           APEX1501 v20231214
Platform:          Linux x86-64, statically linked ELF (no shared lib deps)
File size:         ~7.3 MB
Source:            https://epicapex.tamu.edu/media/w0ecjadt/apex-1501-linux.zip
Manual:            https://epicapex.tamu.edu/media/pkff4m34/the-apex1501-user-manual-november-2023.pdf
Theory:            https://epicapex.tamu.edu/media/2mwdlhte/the-apex1501-theoretical-documentation-january-2023.pdf
```

The binary is statically linked — no installation, just copy it to your run
directory (or invoke from anywhere). The binary **always** opens its input files
from the **current working directory** and **always** writes outputs to the current
working directory. There is no command-line argument parsing.

### Validation that the binary works

```bash
# Run preflight (verifies binary, example dataset, control files)
python preflight_check.py
```

Expected output:
```
[OK] APEX1501 binary found at .../apex1501
[OK] APEX1501 binary is executable
[OK] Example dataset found in examples/
[OK] All required control files present (APEXFILE.DAT, APEXCONT.DAT, ...)
[OK] preflight passed — APEX is ready to run
```

---

## File ecosystem (FORTRAN FIXED-WIDTH FORMATS — COPY, DON'T GENERATE)

APEX 1501 is a Fortran-90 model. **Every input file is a Fortran fixed-format
text file with rigid column positions**. The single most important rule:

> **NEVER WRITE APEX INPUT FILES FROM SCRATCH. ALWAYS COPY FROM
> `examples/` AND MODIFY SPECIFIC VALUES IN PLACE.**

The KI ships with a complete validated example dataset in `examples/` derived from
the USDA-ARS published pyAPEXSCU dataset (Maskey et al., grazing study at Marena
ARS station, 35.54°N, 98.05°W, OK). Every tool in `tools/` follows the
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
**S8** | `tools/s8_update_operations.py`   | Edit existing `OPSC*.MGT` / `*.OPC` operation schedules in place
**S9** | `tools/s9_generate_crop_opc.py`   | Generate APEX0806 crop operation schedules and wire `OPSCCOM.DAT`

Stage skill docs:
- [S1 setup workspace](docs/s1_setup_workspace.md)
- [S2 convert forcing](docs/s2_convert_forcing.md)
- [S3 build soil](docs/s3_build_soil.md)
- [S4 update site](docs/s4_update_site.md)
- [S5 update control](docs/s5_update_control.md)
- [S6 run APEX](docs/s6_run_apex.md)
- [S7 parse output](docs/s7_parse_output.md)
- [S8 update operations](docs/s8_update_operations.md)
- [S9 generate crop OPC](docs/s9_generate_crop_opc.md)

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

## Unit Conversion Table (template §8)

Exact I/O shapes live in `docs/format_spec.yaml` and the dag. This unit table
summarizes the conversions and unit traps this KI already documents; do not
replace it with remembered conventions.

| Variable | Source unit (verified or expected) | APEX model unit | Conversion / handling | Type |
|---|---|---|---|---|
| Latitude / longitude | decimal degrees | decimal degrees | use as-is; southern hemisphere is negative | identity |
| Elevation | ft, m, or source DEM unit | m | ft × 0.3048 when source is feet | multiplicative |
| Channel length CHL / RCHL | m, km, or mi | km | convert source length to km before writing `*.SUB` | unit conversion |
| Channel slope CHS | percent, degrees, or fraction | m/m fraction | percent ÷ 100; do not write 5.0 for 5% | unit conversion |
| Watershed area WSA | m², km², ac, or ha | ha | convert source area to hectares before writing `*.SUB` | unit conversion |
| Daily precipitation | source forcing native unit | mm/day | CMFD 3-hr kg/m²/s ×10800 per step, sum 8 steps; MSWX 3-hr mm/3hr sum 8 steps | accumulation |
| Tmax / Tmin | K or °C | °C | K − 273.15; °C unchanged | additive or identity |
| Solar radiation SRAD | W/m² or MJ/m²/day | MJ/m²/day | daily mean W/m² × 0.0864; MJ/m²/day unchanged | multiplicative |
| Wind speed | m/s, mph, or km/h | m/s | convert source wind to m/s | unit conversion |
| Relative humidity | percent or fraction | fraction (0-1) | percent ÷ 100 | unit conversion |
| CO2 | ppmv or ppm | ppm | ppmv is treated as ppm by volume | identity |
| Saturated K (Ksat) | source soil hydraulic unit | mm/h | convert to mm/h before writing `*.SOL` | unit conversion |
| Soil bulk density | kg/m³ or g/cm³ | g/cm³ (= Mg/m³) | kg/m³ ÷ 1000 | multiplicative |
| Soil organic C | g/kg or percent by weight | percent by weight | g/kg ÷ 10 | multiplicative |
| Soil pH | dimensionless | dimensionless | use as-is | identity |
| N applied | lb/ac or kg/ha | kg/ha | lb/ac × 1.12085; kg/ha unchanged | multiplicative |
| Crop yield output `YLDG` | APEX output | t/ha dry matter | do not compare directly to bu/ac or kg/ha without conversion | output unit |
| Above-ground biomass output `BIOM` | APEX output | see `dag.yaml` | use dag unit when scoring | output unit |
| Water yield output `WYLD` | APEX output | mm, or m³ in mass balance block | check output block before scoring | output unit |
| Evapotranspiration output `ET` | APEX output | see `dag.yaml` / output block | check output block before scoring | output unit |
| Deep percolation output `DPRK` | APEX output | see `dag.yaml` / output block | check output block before scoring | output unit |
| Sediment yield output `Y` | APEX output | t/ha | do not compare directly to t/ac or kg/ha without conversion | output unit |

### Sign Conventions and Output Units

APEX reports agronomic and hydrologic annual outputs as positive magnitudes in the
printed output tables used by `tools/s7_parse_output.py`. For water-balance checks,
use the documented closure convention:

`PCP ≈ WYLD + ET + DPRK + ΔS` within ±5%.

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

## Output Description (template §6)

Source of truth: `dag.yaml`. This section restates the KI's dag facts for readers;
if this section and `dag.yaml` ever disagree, `dag.yaml` wins.

**Headline output** (dag `validation_rank: 1`):

> `YLDG` — Crop grain yield, dry matter (harvest index x above-ground biomass, reduced by water stress and pest factor) (`t/ha`)

| Output variable (dag `var`) | Rank | Unit | Description / role |
|---|---:|---|---|
| `YLDG` | 1 | `t/ha` | Crop grain yield, dry matter (harvest index x above-ground biomass, reduced by water stress and pest factor) |
| `BIOM` | see `dag.yaml` | see `dag.yaml` | Other dag output |
| `LAI` | see `dag.yaml` | see `dag.yaml` | Other dag output |
| `WYLD` | see `dag.yaml` | see `dag.yaml` | Other dag output |
| `ET` | see `dag.yaml` | see `dag.yaml` | Other dag output |
| `DPRK` | see `dag.yaml` | see `dag.yaml` | Other dag output |
| `Y` | see `dag.yaml` | see `dag.yaml` | Other dag output |
| `N losses (leaching / runoff / sediment)` | see `dag.yaml` | see `dag.yaml` | Other dag output |
| `P losses (soluble runoff / sediment / tile)` | see `dag.yaml` | see `dag.yaml` | Other dag output |
| `outlet hydrograph (HYC)` | see `dag.yaml` | see `dag.yaml` | Other dag output |

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

## Validated Results (template §11)

### Test case: Bengbu China corn

| Property | Value |
|---|---|
| Location | Bengbu, China |
| Crop | corn |
| Simulated yield | 6.21 t/ha |
| Observed yield | 5.6 t/ha |
| Reported bias | +11% |
| Validation status | `validated` |

### Performance Metrics — judged against the field's bar, not intuition

Source of truth: `docs/validation_convention.yaml`. The convention wins over
remembered thresholds. Every band below carries the citation key supplied by the
convention.

| Dag variable | Metric | Direction | Very good | Good | Satisfactory | Citation key |
|---|---|---|---:|---:|---:|---|
| `YLDG` | `pbias` | zero_centered | 5.0 | 10.0 | 15.0 | `jiang2021` |
| `YLDG` | `nrmse` | minimize | 10.0 | 20.0 | 30.0 | `jiang2021` |
| `BIOM` | `nrmse` | minimize | 10.0 | 20.0 | 30.0 | `jiang2021` |
| `BIOM` | `pbias` | zero_centered | 5.0 | 10.0 | 15.0 | `jiang2021` |

For zero-centered `pbias`, compare the absolute bias magnitude to the cited band.
For minimize `nrmse`, lower values are better. No uncited threshold is implied for
any metric or output not listed in `docs/validation_convention.yaml`; write
`no cited threshold` when the convention has a null band.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|---|---|---|---|
| Forcing | CMFD weather pipeline | validated for the Bengbu China corn case | Prepared through KI tools |
| Soil | HWSD soil pipeline | validated for the Bengbu China corn case | Prepared through KI tools |
| Management / crop calendar | GGCMI calendar and APEX0806-compatible operation schedules | validated for the Bengbu China corn case | Use `tools/s9_generate_crop_opc.py` for compatible op and fertilizer codes |
| Execution binary | `reference/APEX0806.exe` via Wine | validated | Use v0806 for crop-yield work |
| Parsing and scoring | `tools/s7_parse_output.py`; `docs/validation_convention.yaml` | validated convention available | Score against cited bars, not intuition |

---

## References

- APEX1501 User Manual (November 2023), Steglich et al., Texas A&M AgriLife
  https://epicapex.tamu.edu/media/pkff4m34/the-apex1501-user-manual-november-2023.pdf
- APEX1501 Theoretical Documentation (January 2023), Williams et al.
  https://epicapex.tamu.edu/media/2mwdlhte/the-apex1501-theoretical-documentation-january-2023.pdf
- Williams, J. R., et al. (2008). The APEX model. In Watershed Models. CRC Press.
- pyAPEXSCU (Maskey et al.) — published worked example used as our test dataset
  https://github.com/mlmaskey/pyAPEXSCU
