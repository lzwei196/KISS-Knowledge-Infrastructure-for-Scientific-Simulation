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
> 3. **Find working examples** — Look in `examples/` for previous successful runs of
>    this model, or check if the model ships with test/example data
> 4. **Fix the tool** — Now that you know what "correct" looks like, make targeted fixes
>
> Resist the urge to write diagnostic/debug Python scripts. The answers are almost
> always in the official docs and working examples, not in reverse-engineering the binary.

# EPIC (Environmental Policy Integrated Climate) Crop & Field Model — Knowledge Infrastructure

**Package**: `hydrocraft-epic-crop` v2.0.0
**Model**: EPIC 0810 (Linux ELF binary, Intel Fortran 2010 build)
**Source**: USDA-ARS / Texas A&M BREC EPIC distribution
**Binary**: `/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/EPIC/source/repo/epic0810.x`
**Domain**: Field-scale crop growth, soil water/nutrient cycling, erosion, management
**Last updated**: 2026-04-14
**Stats**: 4 tools | 6 skill documents | 18 diagnostic triplets

---

## Overview

EPIC (Environmental Policy Integrated Climate, originally Erosion Productivity
Impact Calculator) is a field-scale, daily time-step model developed by USDA-ARS
to simulate plant growth, soil water and nutrient dynamics, erosion, tillage,
and management on a single homogeneous field. The dissected binary `epic0810.x`
is the EPIC0810 release (Intel Fortran build, 2010), distributed as a stripped
Linux ELF executable with no Wine dependency.

**What EPIC simulates**:
- Plant growth and yield for ~100 crop types via a unified phenology / radiation-use efficiency model
- Daily soil water balance (Hargreaves/Penman PET, Curve Number runoff, Green-Ampt, percolation)
- Soil nitrogen and phosphorus cycling (mineralization, nitrification, denitrification, uptake)
- Wind and water erosion (USLE family, MUSI, RUSLE, MUSLE, MUSS, MUST)
- Carbon cycling (Izaurralde C/N pools)
- Tillage, fertilizer, irrigation, pesticide, harvest operations
- Multi-year crop rotations
- Weather generation from monthly statistics (WXGEN) when daily weather is unavailable

**Key features that distinguish epic0810 from later releases**:
- Uses `RUN0810.SUM` not `RUN1102.SUM`
- Reads `SOIL38K.DAT` not `SOIL35K.DAT`
- Strict numeric format on SOL files — alphabetic structure codes (`A`, `B`, `C`, `D`)
  in soil-structure rows must be replaced with numeric zeros
- File name table (`EPICFILE.DAT`) still references `PARM1102.DAT`, `MLRN1102.DAT`,
  `CMOD1102.DAT`, `PRNT1102.DAT` — file names are not version-locked

---

## Installation

The EPIC binary is shipped pre-compiled. No build step required.

```bash
chmod +x /home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/EPIC/source/repo/epic0810.x
file /home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/EPIC/source/repo/epic0810.x
# ELF 64-bit LSB executable, x86-64, dynamically linked, stripped
```

Required Python dependencies for the KI tools:
```bash
pip install numpy pandas matplotlib pyyaml
```

The example/template files live in:
```
/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/EPIC/source/repo/epic1102_example_files_20221002/
```

---

## Pipeline (6 stages)

| # | Stage | Tool | Purpose |
|---|-------|------|---------|
| 0 | Workspace prep | `tools/run_epic_workspace.py` (setup_workspace) | Copy template files, fix SOIL38K alias, sanitize SOL alpha codes |
| 1 | Weather conversion | `tools/convert_forcing_to_dly.py` | CMFD/MSWX/NASA POWER → EPIC `.DLY` (year, month, day, srad, tmax, tmin, prcp, rh, ws) + `.WP1` monthly stats + `.WND` wind stats |
| 2 | Soil conversion | `tools/convert_soil_to_sol.py` | HWSD + ROSETTA → EPIC `.SOL` (header, albedo/hyd-grp, 19 properties × 6 layers) |
| 3 | Site / OPC update | `tools/run_epic_workspace.py` (update_site) | Modify `.SIT` lat/lon/elev and `.OPC` operation dates |
| 4 | Execution | `tools/run_epic_workspace.py` (run) | Update `EPICCONT.DAT`/`EPICRUN.DAT`, copy template, execute binary |
| 5 | Output parsing | `tools/parse_epic_output.py` | Parse `.ACY`, `.DGN`, `.ANN`, `.OUT` to pandas DataFrames |

---

## File Formats

### EPICCONT.DAT — Simulation Control (line 1)

Fixed-width: `[NBYR:4][IYR:4][IMO:4][IDA:4][NGN:4]...`

| Cols | Variable | Meaning |
|------|----------|---------|
| 1–4 | NBYR | Number of years to simulate |
| 5–8 | IYR | Start year (4-digit) |
| 9–12 | IMO | Start month (1-12) |
| 13–16 | IDA | Start day (1-31) |

Example: `  15 1930   1   1   3 2345   0   0   1   4   0   0   0   0   0   0   0   0   0   0`
(15 years starting Jan 1 1930)

### EPICRUN.DAT — Per-Run Site Selection

Format: `{site_id_padded_9} {NSIT} {NWP1} {NWND} {NWP5} {NSOL} {NOPS} {NDLY}/`

The seven integers are 1-indexed line numbers into the corresponding `*COM.DAT`
or `*USEL.DAT` list files (SITECOM, WPM1USEL, WINDUSEL, WPM5US, SOILCOM, OPSCCOM,
WDLSTCOM). Trailing `/` is required by Fortran namelist read.

### EPICFILE.DAT — Logical→Physical File Map

```
 FSITE    SITECOM.DAT       <- list of .SIT files
 FWPM1    WPM1USEL.DAT      <- list of monthly weather (.WP1) files
 FWPM5    WPM5US.DAT        <- monthly weather variability
 FWIND    WINDUSEL.DAT      <- wind direction/speed climatology
 FCROP    CROPCOM.DAT       <- crop parameter database
 FTILL    TILLCOM.DAT       <- tillage equipment database
 FPEST    PESTCOM.DAT       <- pesticide database
 FFERT    FERT2012.DAT      <- fertilizer database
 FSOIL    SOILCOM.DAT       <- list of .SOL files
 FOPSC    OPSCCOM.DAT       <- list of .OPC files
 FPARM    PARM1102.DAT      <- 112 global parameters (NOT 0810-named, name unchanged)
 FMLRN    MLRN1102.DAT      <- machine learning (legacy stub)
 FPRNT    PRNT1102.DAT      <- output type toggles
 FCMOD    CMOD1102.DAT      <- crop modification overrides
 FWLST    WDLSTCOM.DAT      <- list of .DLY files
```

### .DLY — Daily Weather Input

Fixed-width Fortran format: `(I6,2I4,6F6.2)`

| Col | Width | Variable | Unit | Description |
|-----|-------|----------|------|-------------|
| 1 | 6 | year | – | 4-digit year |
| 2 | 4 | month | – | 1–12 |
| 3 | 4 | day | – | 1–31 |
| 4 | 6 | srad | MJ/m²/day | Solar radiation |
| 5 | 6 | tmax | °C | Max temperature |
| 6 | 6 | tmin | °C | Min temperature |
| 7 | 6 | prcp | mm/day | Precipitation |
| 8 | 6 | rh | fraction (0-1) | Relative humidity |
| 9 | 6 | ws | m/s | Wind speed |

Example record: `  1922   1   1  10.7  8.33 -3.33  0.00  0.71  2.08`

The file ends with one metadata line:
`STATION = NCRDU  STA ID = 317079  STATE = NC  CO = wake  LAT = 35.87  LONG = -78.78  ELEV =  133.5  Y-M-D 1995-12-31`

### .WP1 — Monthly Weather Statistics (14 × 12 = 168 values)

Generated from a multi-year .DLY by computing monthly OBMX, OBMN, RST2 (rain),
OBSL (sunshine), RH, UAVO (wind), SDTMX, SDTMN, RST2 std, DAYP, RST3, PRW1, PRW2, WI.

### .WND — Wind direction/speed climatology

16 wind directions × 12 months of frequency, plus 12 monthly average wind speeds.

### .SOL — Soil Profile (Strict numeric — no alphabetic structure codes)

Line 1: header text (free format, ignored by binary)
Line 2: 10 site-level reals (8.2f each):
  `albedo  hyd_grp  depth  min_thick  spl_factor  rcr  cn2  ridge  rsd  zsr`
Line 3: 10 reals — additional site parameters
Lines 4–46+: 19 soil-property rows, one row per property, columns = layers (6)

**Soil layer properties order** (each 6 values, `(6F8.2)` or `(6F8.3)`):
1. Layer depth from surface (m)
2. Bulk density (g/cm³)
3. Wilting point (m³/m³)
4. Field capacity (m³/m³)
5. Sand (%)
6. Silt (%)
7. Initial soil water (m³/m³)
8. Soil organic N concentration (g/t)
9. pH
10. Sum of bases (cmol/kg)
11. Organic C (%)
12. CaCO₃ (%)
13. CEC (cmol/kg)
14. Coarse fragments (%)
15. Initial NO₃ (g/t)
16. Initial labile P (g/t)
17. Crop residue (t/ha)
18. Bulk density (oven-dry)
19. Saturated hydraulic conductivity (mm/h)

**CRITICAL TRAP**: Some EPIC1102 example SOL files contain rows with alphabetic
structure codes (`A`, `B`, `C`, `D`) — for example line 48 of `umstead.SOL`:
`       A       A       A       A       A       A`. The EPIC0810 binary
**rejects these with `forrtl: severe (64): input conversion error`**.
Replace every alphabetic token with a numeric zero (`    0.00`) before running.
The setup_workspace tool does this automatically.

### .OPC — Operation Schedule

Fixed-width 15-column table; columns 1–7 are integers, 8–15 are reals.

| Cols | Variable | Description |
|------|----------|-------------|
| 1–3 | Yid | Relative year (1 = first year) |
| 4–6 | Mn | Month |
| 7–9 | Dy | Day |
| 10–14 | CODE | Operation type code |
| 15–19 | TRAC | Equipment ID |
| 20–24 | CRP | Crop code from CROPCOM.DAT |
| 25–29 | XMTU | Context (fert ID, layer, etc.) |
| 30+ | OPV1..OPV8 | 8.2f each — operation parameters |

Operation codes:
- `2`, `3`, `4`, `146`: Planting (OPV1 = potential heat units, °C·day)
- `650`: Harvest
- `71`: Fertilizer application (XMTU=fert ID, OPV1=rate kg/ha)
- `72`: Auto-irrigation activation
- `41`: Residue management
- `9`: Fallow

### .SIT — Site information

7 lines of metadata: title, prototype name, site ID, then site reals
(lat, lon, elevation, slope length, slope steepness, etc.).

---

## Output File Formats

### `<run>.OUT` — General output (always produced)

Multi-section ASCII report with header, parameter listing, weather summary,
crop summary, annual rotation table. Best read line-by-line.

### `<run>.ACY` — Annual Crop Yield

Skip first 10 header lines, then whitespace-delimited columns:
`YR RT# CPNM YLDG YLDF WCYD HI BIOM RW YLN YLP YLC FTN FTP IRGA IRDL WUEF GSET CAW CRF CQV COST COOP RYLG RYLF PSTF WS NS PS KS TS AS SS PPOP IPLD IGMD IHVD`

Key variables: YLDG (grain yield t/ha), BIOM (above-ground biomass t/ha),
HI (harvest index), WUEF (water use efficiency), WS/NS/PS (water/N/P stress days).

### `<run>.DGN` — Daily General

Skip first 10 header lines, columns:
`Y M D PDSW TMX TMN RAD PRCP VPD PET ET PEP EP Q CN SSF PRK QDRN IRGA QIN PRKN TNO3 NO31 PRK1 LN31 HUI LAI BIOM YLDF UNO3 LSN LMN BMN HSN HPN TWN`

Key variables: Q (runoff mm), ET (mm), LAI, BIOM (t/ha), HUI (heat unit index 0–1).

### `<run>.ANN` — Annual summary

Skip first 10 header lines:
`RUN YR AP15 PMTE TMX TMN PRCP IRGA PET ET Q DN LIME DN2O FULU`

### Other output files (toggled by PRNT1102.DAT)

`.ACM` (annual C/N mass), `.DHS` (daily hydrology), `.DWC` (daily water chem),
`.MFS`/`.MPS` (monthly summaries), `.SOT` (soil organic turnover), `.MCM`,
`.SCO`, `.DTP`, `.SUM`, `.DPS`, `.ACO`, `.DSL`, `.MWC`, `.ABR`, `.ATG`, `.MSW`,
`.APS`, `.DGZ`, `.DNC`, `.ASL`, `.DDN`.

---

## Unit Trap Table

| Variable | Source unit | EPIC unit | Conversion | Trap |
|----------|-------------|-----------|------------|------|
| Solar radiation (Daymet) | W/m² | MJ/m²/day | `srad * dayl / 1e6` | Omitting daylength gives ~86× overestimate |
| Solar radiation (CMFD) | W/m² (3-h mean) | MJ/m²/day | `mean(W/m²) * 86400 / 1e6` | Using 3-hr instantaneous → ~24× over/under |
| Temperature (CMFD) | K | °C | `T - 273.15` | Kelvin in DLY → impossible PET, model crashes |
| Precipitation (CMFD 3h) | mm/3h | mm/day | `sum(8 timesteps)` | Mean instead of sum → 8× under |
| Relative humidity (NASA POWER) | % | fraction (0-1) | `RH / 100` | Forgetting /100 → RH=70 not 0.70, vapour-deficit blows up |
| Wind speed | m/s | m/s | none | – |
| Wind speed (NASA POWER 10m) | m/s @ 10m | m/s @ 10m | none | EPIC expects 10m height; converting to 2m corrupts ET |
| Soil bulk density | g/cm³ | g/cm³ | none | Using kg/m³ → 1000× error |
| Layer depth (HWSD) | cm | m | `cm/100` | EPIC0810 SOL row 1 expects metres, not centimetres |
| Saturated K (ROSETTA) | cm/day | mm/h | `cm/day * 10/24` | Wrong factor → infinite percolation |
| Organic matter → OC | % OM | % OC | `OM / 1.724` | Van Bemmelen factor, not a direct copy |
| Fertilizer rate | kg/ha N | kg/ha element | none | If using NH₄-N table, must convert from compound to element |
| Elevation | m | m | none | Using ft → 0.3048× error in WXGEN |
| PHU (potential heat units) | °C·day | °C·day | accumulate Tavg-Tbase | Wrong PHU → crop never matures or matures early |
| Slope steepness | fraction (m/m) | fraction | none | Using degrees or % without conversion |
| CMFD lat/lon | 0.1° China grid | EPIC site degrees | direct | Out-of-domain → silent zero forcing |

---

## Workspace Layout (after run_epic_workspace.setup)

```
/tmp/epic_workspace_<uuid>/
├── epic0810.x                 # binary
├── EPICCONT.DAT               # control (start year, duration)
├── EPICRUN.DAT                # run line
├── EPICFILE.DAT               # logical→physical file map
├── PARM1102.DAT               # 112 global parameters
├── PRNT1102.DAT               # output toggles
├── CROPCOM.DAT, FERT2012.DAT, ...   # databases
├── SITECOM.DAT, SOILCOM.DAT, OPSCCOM.DAT, WDLSTCOM.DAT  # list files
├── WPM1USEL.DAT, WPM5US.DAT, WINDUSEL.DAT  # weather climatology
├── SOIL35K.DAT, SOIL38K.DAT   # soil database (38K is alias of 35K)
├── umstead.SIT, umstead.SOL, umstead.OPC  # site files
├── NCRDU.DLY                  # daily weather
└── umstead_0.OUT/.ACY/.DGN/.ANN/...  # outputs after run
```

---

## Tool Reference

| Tool | Purpose | Key entry points |
|------|---------|------------------|
| `tools/convert_forcing_to_dly.py` | Build `.DLY`, `.WP1`, `.WND` from CMFD/MSWX/NASA POWER | `convert(source, lat, lon, year1, year2, out_dir)` |
| `tools/convert_soil_to_sol.py` | Build `.SOL` from HWSD + ROSETTA | `convert(lat, lon, sol_path)` |
| `tools/run_epic_workspace.py` | Setup workspace, run binary, collect outputs | `setup_workspace`, `run`, `sanitize_sol` |
| `tools/parse_epic_output.py` | Parse `.ACY`, `.DGN`, `.ANN` to pandas | `parse_acy`, `parse_dgn`, `parse_ann` |

All tools share the validate→process→validate pattern. Forcing converter calls
`ki_tools_common.load_forcing.load_daily_forcing` so CMFD/MSWX/NASA POWER all work
through one entry point. Soil converter calls `ki_tools_common.soil_utils.lookup_hwsd`
+ `rosetta_vgn`.

---

## Quick Start

```python
from tools.run_epic_workspace import setup_workspace, run, collect_outputs
from tools.parse_epic_output import parse_acy, parse_dgn

# 1. Build a clean workspace from the templates
ws = setup_workspace("/tmp/epic_run1")

# 2. (optional) Update site coordinates / start year / duration
#    (here we accept the umstead defaults)

# 3. Run the binary
result = run(ws, site_id="umstead_0", timeout=300)
assert result["status"] == "completed", result

# 4. Parse outputs
acy = parse_acy(f"{ws}/umstead_0.ACY")     # pandas DataFrame
dgn = parse_dgn(f"{ws}/umstead_0.DGN")
print("Mean LAI:", dgn["LAI"].mean())
print("Mean ET:", dgn["ET"].mean(), "mm/day")
```

---

## Calibration Notes

EPIC has 112 global parameters in PARM1102.DAT and 60+ crop-specific rows in
CROPCOM.DAT. Common targets:

- PARM(1)–PARM(5): Erosion/runoff coefficients
- PARM(20)–PARM(30): N/P cycling
- PARM(34): Heat unit scheduling
- CROPCOM HI: harvest index
- CROPCOM WA: radiation use efficiency
- CROPCOM DMLA: maximum LAI

Use SALib or PyGMO with `parse_acy()` as the objective function reader.

---

## Source Code & References

- USDA-ARS / Texas A&M AgriLife BREC: https://epicapex.tamu.edu/
- EPIC user manual (PDF): EPIC1102 user manual is the closest published reference;
  most file formats are unchanged from 0810
- Williams, J.R. (1995): "The EPIC Model" in *Computer Models of Watershed Hydrology*
- Geo-EPIC toolkit (geospatial wrapper, Python): https://github.com/smarsGroup/geo_epic_win

---

## Data Preparation

**Forcing**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for
unified CMFD / MSWX / NASA POWER access. EPIC needs daily timestep; the converter
aggregates 3-hourly CMFD by `sum(prcp)`, `mean(temp/srad/rh/ws)`.

**Soil**: Use `from ki_tools_common.soil_utils import lookup_hwsd, rosetta_vgn`.
The HWSD lookup returns sand/clay/silt/OM/bulk_density/CEC/pH/CaCO3 per layer,
and ROSETTA returns van Genuchten + Ksat. Map these into the EPIC 19-property
profile via the helper in `tools/convert_soil_to_sol.py`.

**Land cover**: EPIC uses its own crop codes (CROPCOM.DAT). For multi-crop
sites use a separate `.OPC` per cropping system; for natural vegetation
the umstead 80-year mixed pine/hardwood OPC is a good template.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md`, `data_ki/HWSD/SKILL.md`,
`data_ki/FAOSTAT/SKILL.md`, `data_ki/SPAM/SKILL.md`.

---

## Known Limitations of EPIC0810

- No LULCC dynamics; one crop/rotation per simulation
- Single-point field scale (no spatial interaction)
- Strict Fortran fixed-format I/O (no error tolerance for malformed inputs)
- WXGEN weather generator works only with `.WP1`/`.WND`/`.WP5` databases
- Does not model perennial reseeding without explicit OPC events
