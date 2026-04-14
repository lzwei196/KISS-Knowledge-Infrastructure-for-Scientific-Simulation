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
> 2. **Read official docs** — Check the model's own documentation (PDF manual, README,
>    official examples) for expected input formats, variable names, and units
> 3. **Find working examples** — Look in `examples/` for the validated working case
>    (FARM 1 AT WRE OK, 35.54N -98.05W, 1979-1993). Compare your inputs against these.
> 4. **Fix the tool** — Now that you know what "correct" looks like, make targeted fixes
>
> Resist the urge to write diagnostic/debug Python scripts. The answers are almost
> always in the official docs and working examples, not in reverse-engineering the binary.

---

# APEX 1501 (Agricultural Policy / Environmental eXtender) — Knowledge Infrastructure

**Model**: APEX1501 v20231214 (released 2023-12-14)
**Distributor**: Texas A&M AgriLife / Blackland Research and Extension Center
**Source**: https://epicapex.tamu.edu/software/
**Language**: Fortran 90 (Intel Fortran compiled, statically linked ELF)
**Domain**: Field- and watershed-scale agronomy / hydrology / water-quality
**Validation status**: `analytic` — successfully runs the published USDA-ARS WRE
Mesonet OK pasture-grazing example dataset (1.63 ha subarea, 1979–1993 simulation).

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
APEX 1501 binary:  /home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/APEX/source/repo/Apex 1501 - Linux/apex1501
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
cd /mnt/disk1/Hydrocraft_server/models/APEX/knowledge_infrastructure
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
update_control(ws, year1=2010, year2=2015, ngn=2345)             # read all 5 weather vars
run(ws)                                                           # binary
df = parse(ws)                                                    # → DataFrame of annual results
```

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

## References

- APEX1501 User Manual (November 2023), Steglich et al., Texas A&M AgriLife
  https://epicapex.tamu.edu/media/pkff4m34/the-apex1501-user-manual-november-2023.pdf
- APEX1501 Theoretical Documentation (January 2023), Williams et al.
  https://epicapex.tamu.edu/media/2mwdlhte/the-apex1501-theoretical-documentation-january-2023.pdf
- Williams, J. R., et al. (2008). The APEX model. In Watershed Models. CRC Press.
- pyAPEXSCU (Maskey et al.) — published worked example used as our test dataset
  https://github.com/mlmaskey/pyAPEXSCU
