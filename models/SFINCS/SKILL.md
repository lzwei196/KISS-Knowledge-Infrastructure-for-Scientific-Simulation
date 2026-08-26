---
name: sfincs
description: >-
  SFINCS reduced-physics solver (Leijnse et al. 2021; local-inertial / SSWE), subgrid per
  van Ormondt et al. 2025. Covers 2D shallow-water flood inundation (depth and extent)
  within a local domain; Pluvial flooding from local precipitation; Fluvial flooding from
  river discharge / source-point inflow; Coastal/compound flooding from tidal/surge
  water-level boundary (datum-dependent). Use when the task involves running, configuring,
  calibrating or interpreting SFINCS.
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
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
SFINCS forcing tools are in `tools/s4_forcing/` in this KI:
- `tools/s4_forcing/prepare_sfincs_rainfall.py` — Converts CMFD/MSWX precipitation to SFINCS NetCDF rainfall (mm/3hr → mm/hr)
- `tools/s4_forcing/cama_to_sfincs_boundary.py` — Converts CaMa-Flood output to SFINCS boundary conditions (water level or discharge)

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.

---

# SFINCS v2.x (Super-Fast INundation of CoastS) — Knowledge Infrastructure

**Package**: `hydrocraft-sfincs` v1.0.0
**Model**: SFINCS v2.x (Deltares)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-22
**Stats**: 9 tools | 8 skill documents | 28 diagnostic triplets | 12 error log entries | ~2,379 lines of validated Python
**Validation**: Step 3 — Bengbu (Huai River) flood test (2026-03-22) — 384x455 cells, 100m, 397s, 6.99m max depth, CaMa-Flood cross-validated. Previous: Chaohe (2026-03-21) — 174x171 cells, 5.7s, 7.29m max depth.

---

## Overview

This knowledge infrastructure enables fully autonomous 2D flood inundation simulation using SFINCS on any domain worldwide, integrated with HydroCraft's VIC + CaMa-Flood pipeline. The 8 validated tools handle domain setup, DEM processing, forcing conversion, configuration, execution, and post-processing.

**What SFINCS does**: Reduced-complexity 2D shallow water solver for rapid flood inundation modeling:
- **Coastal flooding**: Storm surge, tides, sea-level rise, wave setup
- **Fluvial flooding**: River overflow from CaMa-Flood discharge as boundary condition
- **Pluvial flooding**: Rainfall-driven urban/rural flooding from CMFD/MSWX precipitation
- **Compound flooding**: Combined coastal + fluvial + pluvial (primary use case)
- **Subgrid**: Coarse computational grid (50-200m) with fine bathymetry resolution (5-10m)

**Key difference from CaMa-Flood**: CaMa-Flood routes water through 15-arcmin (~28km) river networks. SFINCS resolves flood depth and extent at 10-200m within a local domain. They are complementary: CaMa-Flood provides river boundary conditions for SFINCS.

**HydroMT-SFINCS**: The Python model builder (`hydromt_sfincs` — **NOT actually installed on this server as of 2026-08-05: `import hydromt_sfincs` -> ModuleNotFoundError**; the binary formats in 'Critical Domain Knowledge' item 8 were therefore re-derived directly from the solver) provides automated grid generation, DEM processing, and Manning's n from land cover. The validated tools wrap HydroMT-SFINCS calls and add HydroCraft-specific validation, unit conversion, and coupling logic.

---

## Installation

### Binary

```
SFINCS solver:    model/sfincs/bin/sfincs
Version:          v2.3.2 mt. Faber+ (compiled 2026-03-21)
Source:           github.com/Deltares/SFINCS main branch (GPL-3.0)
Build:            gfortran 13.3 + libnetcdff 4.6.0
Dependencies:     libnetcdff7, libgfortran5, libnetcdf19, libhdf5 (system packages)
Validated:        Chaohe basin flood test (174x171, 100m, 5.7s, 7.29m max depth) + 50x50 flat test
```

**To compile from source** (if binary not yet built):
```bash
cd /tmp
curl -sL -o sfincs.tar.gz https://github.com/Deltares/SFINCS/archive/refs/heads/main.tar.gz
tar xzf sfincs.tar.gz
cd SFINCS-main/source
# Install autotools if needed: sudo apt install autoconf automake libtool
bash build_gfortran_cpu.sh
cp src/sfincs KISSPATH_BINARIES/sfincs/bin/sfincs
chmod +x KISSPATH_BINARIES/sfincs/bin/sfincs
```

### Python dependencies (all in HydroCraft venv)

```
hydromt_sfincs==1.2.2, rasterio, xarray, geopandas, numpy, scipy, netCDF4, pyproj, matplotlib
```

### CLI Usage

SFINCS reads `sfincs.inp` from the current working directory. No command-line arguments.
```bash
cd /path/to/run_dir   # Must contain sfincs.inp and all referenced files
/path/to/sfincs       # Reads sfincs.inp, writes output to same directory
```

For parallel: `export OMP_NUM_THREADS=4; /path/to/sfincs`

---

## Pipeline (8 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 1 | Domain setup | `setup_sfincs_domain` | Define grid from shapefile/bbox, auto-UTM, compute resolution |
| 2 | Topography | `build_sfincs_topobathy` | Resample DEM to grid, build mask (active/outflow/inactive) |
| 3 | Roughness | `build_sfincs_roughness` | Manning's n from AVHRR land cover or uniform value |
| 4 | Forcing & BC | `prepare_sfincs_rainfall`, `cama_to_sfincs_boundary` | Precipitation (mm/hr) + river discharge/water level BC |
| 5 | Structures | (manual) | Optional: levees (sfincs.thd), weirs, drainage |
| 6 | Configuration | `generate_sfincs_inp` | Assemble sfincs.inp with CFL-stable timestep |
| 7 | Execution | `run_sfincs` | Preflight checks + run binary + output validation |
| 8 | Post-processing | `extract_sfincs_results`, `plot_sfincs_flood_map` | Flood depth/extent maps, statistics, GeoTIFF export |

### Parallelism

Stages 2, 3, 4 can run in parallel after stage 1.
Stage 5 is optional. Stage 6 depends on 2+3+4+(5).
Stage 7 depends on 6. Stage 8 depends on 7.

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `setup_sfincs_domain` | s1 | `tools/s1_domain/setup_sfincs_domain.py` | 210 | Grid from shapefile/bbox, auto-UTM, CFL dt estimate |
| `build_sfincs_topobathy` | s2 | `tools/s2_topobathy/build_sfincs_topobathy.py` | 300 | DEM to sfincs.dep/msk/ind; auto-selects China DEM / **BedMachine Greenland+Antarctica** / GLO-30. `--min_elev`, `--outflow_max_elev` (dt_v019) |
| `build_sfincs_roughness` | s3 | `tools/s3_roughness/build_sfincs_roughness.py` | 200 | AVHRR land cover to Manning's n map |
| `prepare_sfincs_rainfall` | s4 | `tools/s4_forcing/prepare_sfincs_rainfall.py` | 270 | CMFD/MSWX to NetCDF precip (mm/3hr -> mm/hr) |
| `cama_to_sfincs_boundary` | s4 | `tools/s4_forcing/cama_to_sfincs_boundary.py` | 290 | CaMa-Flood outflw/sfcelv to sfincs.src/.dis or .bnd/.bzs |
| `hydat_to_sfincs_boundary` | s4 | `tools/s4_forcing/hydat_to_sfincs_boundary.py` | 300 | **OBSERVED gauge BC**: HYDAT daily Q to sfincs.src/.dis (snapped onto the lowest active channel cells), HYDAT stage stations to sfincs.obs + `obs_levels_<id>.csv` for scoring |
| `generate_sfincs_inp` | s6 | `tools/s6_config/generate_sfincs_inp.py` | 250 | sfincs.inp with auto CFL timestep |
| `run_sfincs` | s7 | `tools/s7_execution/run_sfincs.py` | 210 | Execute with preflight, log check, output validation |
| `extract_sfincs_results` | s8 | `tools/s8_postprocess/extract_sfincs_results.py` | 230 | Parse sfincs_map.nc, flood stats, GeoTIFF export |
| `plot_sfincs_flood_map` | s8 | `tools/s8_postprocess/plot_sfincs_flood_map.py` | 200 | Publication-quality flood depth map |

**Total**: 10 tools, ~2,680 lines of validated Python.

### Skill Documents

| Stage | Document | Covers |
|-------|----------|--------|
| s1 | `docs/s1_domain_skill.md` | Grid resolution vs basin area, UTM selection, buffer sizing |
| s2 | `docs/s2_topobathy_skill.md` | DEM sources, vertical datum, subgrid tables |
| s3 | `docs/s3_roughness_skill.md` | Manning's n by land cover, urban roughness |
| s4 | `docs/s4_forcing_skill.md` | Precipitation units, CaMa-Flood coupling, compound events |
| s5 | `docs/s5_structures_skill.md` | Thin dams, weirs, drainage structures |
| s6 | `docs/s6_config_skill.md` | CFL timestep, physics options, output settings |
| s7 | `docs/s7_execution_skill.md` | Runtime estimation, GPU/CPU, convergence |
| s8 | `docs/s8_postprocess_skill.md` | Flood maps, depth classes, validation |

---

## Validated Results

### Chaohe Basin Flood Test (2026-03-21)
- **Domain**: 174x171 cells at 100m resolution, downstream Chaohe basin (40.50-40.65N, 116.60-116.80E)
- **Event**: Aug 2-12, 2008 monsoon rainfall (88.7mm total from CMFD via VIC forcing)
- **DEM**: China DEM 90m, elevation range 143-1387m
- **Runtime**: 5.7 seconds (OpenMP, 4 threads)
- **Max flood depth**: 7.29m (valley bottoms)
- **Flood volume**: 37.9 million m3
- **Flooded area**: 1,887 cells with depth >0.3m
- **Physical validation**: Water accumulates along NE-SW trending valleys matching terrain structure
- **Bugs found**: 6 (err_006 through err_010 + err_004), all fixed and promoted to triplets dt_v001-dt_v006
- **Key lesson**: First real-basin run exposed 3 FATAL bugs (ind format, precip column, time offset) and 1 SILENT bug (mask=2 draining inland terrain) that the 50x50 synthetic test did not catch

### Bengbu (Huai River) Flood Test (2026-03-22) — Step 3 Validation
- **Domain**: 384x455 = 174,720 cells at 100m resolution, Huai River floodplain near Bengbu city (32.7-33.1N, 117.1-117.5E)
- **Event**: July 2003 monsoon flood (390mm total rainfall from CMFD via VIC forcing)
- **DEM**: China DEM 90m, elevation range 3.5-310.2m (river channel to hills)
- **Runtime**: 397 seconds (OpenMP, 4 threads)
- **Max flood depth**: 6.99m (river channel depressions)
- **Flood volume**: 701 million m3
- **Flooded area**: 44,933 cells with depth >0.3m; 27,107 cells >1.0m; 2,179 cells >3.0m
- **Mass balance**: rain volume 681M m3, stored volume 701M m3 (ratio 1.03 — excellent conservation)
- **CaMa-Flood comparison**: CaMa max flood depth at same location/period = 8.17m at 15-arcmin resolution, consistent with SFINCS 6.99m at 100m resolution. CaMa peak discharge = 6,790 m3/s (confirms major flood event)
- **Validation criteria**: All 5 criteria PASS — (1) non-zero flood depth, (2) max < 20m, (3) water in low areas, (4) no NaN, (5) positive flood volume
- **Bugs found**: 2 new bugs (err_011: extract tool used zsmax instead of hmax, err_012: generate_sfincs_inp used netprecipfile instead of precipfile)
- **Key insight**: The 2003 Huai River flood was one of the worst in the period — 390mm in July produced extensive floodplain inundation. SFINCS results are physically consistent with both CaMa-Flood coarse routing and historical records. This validates SFINCS with real HydroCraft data at a different basin, climate zone (humid subtropical), and terrain (lowland floodplain vs Chaohe mountainous).

---

## What SFINCS can and cannot be VALIDATED against (read before scoring)

SFINCS emits `hmax` (max water depth), `zsmax`/`zs` (water surface elevation),
`point_zs`/`point_h` at his-points, and flood extent derived from `hmax > threshold`
(see `dag.yaml` → `outputs`). A valid comparison needs an observation **of water**:

| Obs type | Valid against | Metric family | Server dataset |
|---|---|---|---|
| Observed inundation mask (SAR) | flood extent | `event_detection` (CSI) | `gfd_v1_4_asia_rice_belt` (monsoon Asia only) |
| Stage / depth gauge in-domain | `point_zs` / `point_h` | `temporal_pattern_match`, `magnitude_accuracy` | `hydat` (Canada), `grdc_caravan` (global, **no China, no Greenland**) |

**How to score against a stage gauge WITHOUT making it circular** (added 2026-08-05).
Forcing SFINCS with the discharge measured AT the gauge and then scoring the water
level at that same gauge is self-referential — the 2026-08-02 reviewer audit rejected
exactly that (`r = 0.954 by construction`). Use TWO stations on the same river:
`hydat_to_sfincs_boundary.py --flow_station <UPSTREAM Q gauge> --obs_stations <DOWNSTREAM stage gauge>`.
The model then has to turn an inflow hydrograph into a stage through its own
bathymetry, roughness and momentum — a real hydrodynamic test.

**Two stations is NECESSARY but NOT SUFFICIENT** (amended 2026-08-05, dt_v024). The
downstream gauge must add INFORMATION, not just a different station name. On the Fraser
Hope -> Agassiz reach the two-station rule was followed exactly and still produced a
degenerate score: with no unforced tributary between them and +0.5% drainage area,
`r(Q_08MF005, h_08MF035) = 0.9939/0.9950`, and a zero-hydraulics power-law rating
`h = 0.0311*Q^0.577 + 10.314` fitted on 2021 scored **NSE 0.9993** on 2022 — above
SFINCS's own 0.9744. The metric measured the rating curve, not the hydraulics.
Before scoring, run:
`tools/s9_validation/screen_obs_independence.py --dis_file … --candidates <id:levels_csv> --cal_period … --val_period … --sim_his …`
It exits NON-ZERO on a degenerate target. Reject any candidate with `r(BC, obs) > 0.95`
or `NSE_model <= NSE_naive`, and quote `information_gain = NSE_model - NSE_naive`
next to every headline number. Prefer a target the BC does not determine: a gauge below
an unforced tributary confluence (Fraser: add `--flow_station 08MF005,08MG013` — Harrison
River, 7890 km², up to 1280 m³/s — and score in the Harrison system), a multi-gauge
longitudinal water-surface profile (08MF072/08MF074/08MF035), an off-channel floodplain
gauge, or the dag's flood-hazard target (`hmax`/extent vs a SAR mask, scored with CSI).
If nothing survives the screen, report a NULL metric with reason
`no_independent_obs_target` — never a degenerate number.
Also keep `qinf` BELOW the mean precipitation intensity: this run set `qinf = 1.0 mm/hr`
against a mean MSWX rainfall of 0.1495 mm/hr (6.7x), which deletes the pluvial term
entirely and leaves the prescribed hydrograph as the sole driver. The screen warns on this.

**Datum registration is mandatory for `zs`** (the dag caveat 'requires shared datum').
HYDAT levels are metres in the station's OWN vertical datum (`STATIONS.DATUM_ID` ->
`DATUM_LIST`; only names containing GEODETIC are comparable with a DEM at all), and a
global DEM over water reports the river SURFACE at acquisition, not the bed. Register the datum from METADATA, never from the obs: run
`register_vertical_datum.py --station <id> --dem_vertical_datum <EGM2008 for GLO-30>`, which
chains STATIONS.DATUM_ID -> DATUM_LIST -> STN_DATUM_CONVERSION (e.g. 08MF035: 35 GEODETIC
SURVEY OF CANADA DATUM -> 605 CGVD2013:EPOCH2010, +0.163 m) and then the CGVD2013 -> DEM-datum
geoid step via PROJ (+0.244 m to EGM2008 here), and FAILS if no chain exists.
The dag sets detrending_options: ['none'] for point_zs, so an obs-FITTED offset is a calibrated
parameter: it disqualifies the period it was fitted on from being reported as a metric. A fitted
offset far larger than the metadata conversion (Fraser 2026-08-05: 1.4035 m fitted vs 0.4073 m
metadata total — 3.4x, or 8.6x the 0.163 m HYDAT gauge-datum step alone) is absorbing GLO-30's
missing channel bathymetry, not registering a datum.

| Surveyed high-water marks | `hmax` / `zsmax` | `magnitude_accuracy` (PBIAS) | — |

**A DEM is NOT a flood observation.** `bedmachine` (`bed_elevation_m`) is a *static*
bedrock + seafloor altitude field — it is indexed under `parameter_sourcing.dem`, has
no time axis, and observes solid earth, not water. It cannot be paired with any SFINCS
output, so a `time_series_comparison` with `nse` on `hmax` vs `bed_elevation_m` is
uncomputable by any model, not a SFINCS failure. Use BedMachine as an **input**
(topobathy, §Data Requirements) and report `scale_comparable: false` if it is handed
to you as the observation.

**Greenland/Antarctic domains currently have no scoreable flood obs on this server**,
and the KI has no ice/snow-melt source term (s4 offers rainfall and CaMa-Flood
discharge only; CaMa-Flood has no Greenland domain), so melt-driven events such as the
11 July 2012 Watson River flood can only be run pluvial-only.

---

## Critical Domain Knowledge (Non-Obvious Facts)

These rules prevent **silent failures** — the model runs without error but results are wrong.

### 1. Mask values: 1=active; 2=WATER-LEVEL boundary; 3=OUTFLOW (dt_v021)

The solver binary states the convention verbatim (`strings sfincs`):

```
inactive=0, active=1, normal_boundary=2, outflow_boundary=3, wavemaker=4
```

**This KI had 2 and 3 swapped until 2026-08-05.** `msk=2` is the *water-level* boundary:
with no `bnd`+`bzs` pair SFINCS holds it at **zs = 0.0 m** and says so in the log
("Setting water level at 0.0 m at mask boundary cells"). `msk=3` is the *absorbing
outflow* boundary and needs no extra file.

* Coastal domain, boundary at mean sea level → `msk=2` is correct (zs=0 IS the datum).
* **Inland river reach (bed at 6–40 m) → `msk=3`.** `msk=2` there is a 40 m head
  gradient that drains the domain to `hmax=0` — the symptom recorded as dt_v005/dt_v019,
  whose old "close the boundary everywhere inland" remedy makes a fluvial run impossible.

`build_sfincs_topobathy.py --outflow_value {2,3}` (default **3**) and
`--outflow_edges n,s,e,w` (open only the downstream side). Verify: `np.unique(msk)` shows
mostly `1` plus `3` along the outlet, and `sfincs_map.nc`'s own `msk` reproduces those
counts exactly.

### 2. Precipitation: ASCII precipfile, NOT NetCDF netprecipfile

SFINCS has two precip input modes: `precipfile` (ASCII: `time_seconds precip_mmhr`) and `netprecipfile` (NetCDF). The NetCDF mode silently fails in some SFINCS versions. Always use ASCII `precipfile`. Format:
```
0.0 2.725272
10800.0 4.773856
21600.0 4.294822
```

### 3. CMFD precipitation is kg/m²/s, NOT mm/3hr

CMFD precip NetCDF attributes say `kg m-2 s-1`. To convert to SFINCS mm/hr: **multiply by 3600** (not divide by 3). This is the #1 unit trap across all models (PREFLIGHT.md). If max precip < 0.01 mm/hr, the units are wrong.

### 4. CaMa-Flood boundary times must be ≥ 0

The `cama_to_sfincs_boundary.py` tool reads CaMa output which may span multiple years. Times in `sfincs.dis` must be seconds since `tref` (≥ 0). Filter CaMa data to the requested simulation period before writing.

### 5. generate_sfincs_inp must reference src/dis/precip files

The config generator checks if files exist before adding them to `sfincs.inp`. Files must be checked in BOTH the current working directory AND the `--output_dir`. Missing references = SFINCS ignores the forcing silently.

### 6. Date filtering for CMFD files

CMFD has hundreds of monthly files. The rainfall tool MUST filter by `YYYYMM` in filename to avoid reading all years. Without filtering: works but takes hours instead of seconds.

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated.

### 1. Precipitation is mm/hr, NOT mm/3hr or mm/day (dt_001, dt_002)

SFINCS expects precipitation rate in **mm/hr**.
- CMFD/MSWX: mm/3hr -> divide by 3
- Some climate models: kg/m2/s (= m/s) -> multiply by 3,600,000
- VIC forcing ASCII: mm/timestep (3-hourly) -> divide by 3

Off by 3x produces flood depths 3x too high. Off by 3.6 million produces zero flooding. Both are silent.

### 2. Vertical datum consistency (dt_004)

DEM elevation and water level boundary conditions MUST use the same vertical datum:
- Copernicus GLO-30 and China DEM: EGM96 geoid heights
- CaMa-Flood sfcelv: relative to geoid (consistent with DEM)
- Tidal models (FES2014): usually MSL or chart datum
- EGM96 geoid vs WGS84 ellipsoid: 20-40m difference depending on location

For fluvial-only (CaMa-Flood BC), this is usually consistent. For coastal (tidal BC), verify datum.

### 3. SFINCS reads from CWD only (dt_017)

The binary has NO command-line arguments. It reads `sfincs.inp` from the current working directory. All file paths in `sfincs.inp` are relative to CWD. Always `cd` to the run directory before executing.

### 4. Mask value 2 = outflow (dt_007)

Edge cells of the active domain MUST have mask=2 (outflow) to allow water to exit. If set to 3 (active), water accumulates at boundaries unrealistically.

### 5. CFL stability (dt_009)

dt must satisfy: `dt <= dx / sqrt(g * h_max)`
For dx=100m, h_max=10m: dt_max = 10.1 seconds. Use 0.75 * dt_max for safety.

### 6. Double-counting precipitation (dt_014)

When coupling VIC/CaMa-Flood with SFINCS, the same rainfall must NOT be applied twice. Choose:
- (a) SFINCS has its own precipitation + CaMa river discharge at boundary only
- (b) SFINCS has VIC/CaMa runoff as source, NO precipitation

### 7. outputformat must be "net" (dt_018)

Add `outputformat = net` to sfincs.inp. Without it, output may be binary, and post-processing tools expect NetCDF (`sfincs_map.nc`).

### 8. The binary maps are COMPRESSED, Fortran-order, SOUTH-up (dt_v023) — THE #1 trap

`sfincs.dep`, `sfincs.msk`, `sfincs.man` and `sfincs.ind` are **not** full rasters.
Proven against the solver on 2026-08-05 by reading `sfincs_map.nc`'s `zb` back and
matching it byte-for-byte to the file that produced it:

```
sfincs.ind : int32 n_active, then n_active 1-BASED flat indices in FORTRAN order
             (n fastest) over an (nmax, mmax) grid whose row 0 is the SOUTH edge
sfincs.dep : n_active float32 — ONLY the active cells, in index order
sfincs.msk : n_active uint8   — ONLY the active cells, in index order
sfincs.man : n_active float32 — ONLY the active cells, in index order
```

File sizes MUST be `dep = man = n_active*4`, `msk = n_active`, `ind = (n_active+1)*4`.

Until 2026-08-05 the KI wrote full `nmax*mmax` grids in **C order with row 0 = NORTH**
for all four. SFINCS reads exactly `n_active` values from each file, so it consumed the
top strip of the raster as if it were the compressed array — the simulated domain was a
scrambled, upside-down fragment, with **no error message**. Measured on a 345×285 Fraser
domain: 25,067 active cells written, **5,406 read**, and every `msk=3` outflow cell lost;
observation points returned `point_zb = -999` and `point_zs` all-NaN, and `hmax` was
uniformly +9999. This is the mechanism behind the Chaohe record's
`flooded_cells == total_cells == 29754, flood_fraction = 1.0`.

Write with `build_sfincs_topobathy.py` (fixed) and read back with its
`read_binary_map(topobathy_dir, nmax, mmax)` helper — never `np.fromfile(...).reshape(nmax, mmax)`.
Post-run check: `np.unique(sfincs_map.nc:msk)` must reproduce
`topobathy_summary.json`'s active/outflow counts.

### 9. Inland vs coastal mask strategy (dt_v005, SUPERSEDED by dt_v021)

Mask value **2** defaults to water level 0.0 m (sea level) — correct only where 0 m *is*
the datum, i.e. a coastal boundary. The old rule ("if min_elevation > 10 m close every
boundary") was a workaround for having 2 and 3 swapped; a closed domain has no outlet and
cannot run a fluvial reach at steady state. **The rule now**: coastal → `msk=2`
(+ `bnd`/`bzs` if you have them); inland → `msk=3` on the downstream edge only
(`--outflow_value 3 --outflow_edges w`).

### 10. Use ASCII precipitation, not NetCDF (dt_v004)

The `precipfile` keyword (ASCII format: time_seconds precip_mmhr) is reliable across all SFINCS versions. The `netprecipfile` keyword (NetCDF) may silently fail to load, showing "Precipitation: no" in the log without crashing. Always prefer ASCII for precipitation.

### 11. VIC forcing column order (dt_v002)

VIC forcing ASCII files have columns: TEMP(0), PREC(1), PRESSURE(2), SW(3), LW(4), VP(5), WIND(6). Column 0 is temperature, NOT precipitation. This is a common confusion because many tools assume column 0 is the primary variable.

### 12. gfortran cleanup SIGABRT is not an error (dt_v006)

SFINCS compiled with gfortran 13.3 may exit with code -6 (SIGABRT) after printing "Simulation finished". The output is valid. Check success by: (1) "Simulation finished" in sfincs.log AND (2) sfincs_map.nc exists with non-zero size. Do not re-run on exit code alone.

### 13. Use `hmax` not `zsmax` for flood depth (dt_v007)

SFINCS output contains both `hmax` (maximum water DEPTH above bed) and `zsmax` (maximum water SURFACE elevation). For flood depth mapping, always use `hmax`. Using `zsmax` gives values equal to terrain elevation + water depth (e.g., 310m instead of 7m), which is meaningless for flood analysis. The extract_sfincs_results.py tool was fixed to prioritize `hmax` over `zsmax`.

### 14. generate_sfincs_inp must use `precipfile` not `netprecipfile` (dt_v008)

The config generator must write `precipfile = sfincs.precip` (ASCII format: `time_seconds precip_mmhr`) when the precipitation file is ASCII. Writing `netprecipfile` when the file is actually ASCII causes SFINCS to silently fall back to "Precipitation: no" — the simulation runs without rainfall, producing zero flooding. This compounds with dt_v004 (NetCDF precip itself is unreliable).

### 15. The venv's netCDF4 CANNOT read SFINCS output — use h5netcdf (dt_v016)

`xr.open_dataset("sfincs_map.nc")` raises `OSError: [Errno -101] NetCDF: HDF error`
in the HydroCraft venv (netCDF4 1.7.4 bundling HDF5 1.14.6) for **every** file SFINCS
writes with its own libnetcdff (HDF5 1.10). The file is fine: `ncdump`, system python
netCDF4, GDAL/rasterio, `h5py` and the `h5netcdf` engine all read it. **Do not re-run
the model — it is a library defect, not a corrupt output.** Open with a fallback:

```python
try:    ds = xr.open_dataset(path)
except OSError: ds = xr.open_dataset(path, engine="h5netcdf")
```

`extract_sfincs_results.py` does this via `open_sfincs_nc()`. The same defect blocks
BedMachine's NSIDC NetCDF — reach those through GDAL (`NETCDF:"file.nc":bed`).

### 16. SFINCS writes +9999 into hmax outside the mask (dt_v017)

Inactive cells get `hmax = +9999` (and `zb = -9999`). Clipping only *negative* values
leaves the positive sentinel in, and the tool then reports **max flood depth 9999 m**
with a flood volume 10⁶ too large — silent and confidently wrong. Mask `|v| >= 9998`
**and** `msk == 0` before computing any statistic.

### 17. Outflow must be elevation-aware, not domain-wide (dt_v019; read dt_v021 FIRST)

Item 9 / dt_v005 gives the inland-vs-coastal rule, but a **mixed** domain (shoreline at
0 m, ridge at 646 m) has no correct global setting: mask=2 cells are held at zs = 0 m,
so an upland edge cell drains the whole domain. Use the new flags:

```bash
# coastal: cut the sea out of the active domain, outflow only on the shoreline
build_sfincs_topobathy.py --min_elev 0.0 --outflow_max_elev 5.0
# inland: closed boundary everywhere
build_sfincs_topobathy.py --outflow_max_elev -9999
```

Also note: with `zsini = 0`, **any active cell below MSL starts full of standing
seawater**, and s8 then reports that as flood depth (measured: 19.98 m of "flood" in a
zero-rainfall smoke run). `--min_elev 0.0` removes it.

### 18. CFL h_max comes from the bathymetry, not from a constant (dt_v020)

`generate_sfincs_inp.py` used to assume `h_max = 10 m` for `dt = 0.75·dx/√(g·h_max)`.
A domain whose bed reaches −135 m carries 135 m of standing water at t=0, where the
limit is 2.7 s, not 10.1 s. Pass `--topobathy_dir` (h_max is then derived from
`topobathy_summary.json` as `max(10, zsini − elevation_min)`) or set `--h_max`.

### 19. MSWX forcing must go through ki_tools_common (dt_v018)

MSWX ships **annual, per-variable** files (`KISSPATH_FORCING/P/P_2012.nc`). The CMFD
discovery logic (`*prec*` in the name + a `YYYYMM` stamp) matches none of them, so
`--source mswx` used to exit 2 with "No precipitation files found" — i.e. it never
worked on any non-China domain. `prepare_sfincs_rainfall.py` now calls
`ki_tools_common.load_forcing.load_hourly_forcing`. Budget ~5 min **per variable per
year**: MSWX annual files are one gzip slab per *global* timestep, so even a
single-point read decompresses the whole year.

### 20. `--bbox` needs the `=` form outside the eastern/northern hemisphere

`--bbox "-51.25,66.94,-50.40,67.12"` dies with `argument --bbox: expected one
argument` — argparse reads the leading `-` as an option flag. Always write
`--bbox="-51.25,66.94,-50.40,67.12"`. The Quick Start below only shows China examples,
where this never bites.

---

## Coupling Points

| # | Source | Target | Variable | Tool |
|---|--------|--------|----------|------|
| c1 | CaMa-Flood | SFINCS | Discharge (m3/s) at river entry | `cama_to_sfincs_boundary` |
| c2 | CaMa-Flood | SFINCS | Water level (m) at coastal boundary | `cama_to_sfincs_boundary` |
| c3 | CMFD/MSWX | SFINCS | Precipitation (mm/hr) | `prepare_sfincs_rainfall` |
| c4 | VIC | SFINCS | Surface runoff (mm/day -> m3/s) | (direct coupling, use with caution) |

### Standard Workflow: VIC -> CaMa-Flood -> SFINCS

1. VIC produces watershed runoff at 0.1-0.25 degree
2. CaMa-Flood routes to river channels, produces daily discharge/stage
3. SFINCS simulates local flood inundation at 10-200m using CaMa discharge as boundary + local rainfall
4. No feedback needed (local flood does not significantly affect upstream hydrology)

---

## Data Requirements

| Data | Source | Status | Path |
|------|--------|--------|------|
| SFINCS binary | Compiled from source | Installed | `model/sfincs/bin/sfincs` |
| China DEM 90m | Local | Available | `data/dem/china_dem_90m/` |
| Copernicus GLO-30 | AWS (auto-download) | Available | Auto-downloaded by hydrobasin |
| BedMachine Greenland v6 | Local (NSIDC) | Available | `data/obs/ice_sheets/bedmachine/BedMachineGreenland-v6.nc` |
| BedMachine Antarctica v4.1 | Local (NSIDC) | Available | `data/obs/ice_sheets/bedmachine/NSIDC-0756_BedMachineAntarctica_*.nc` |
| CMFD forcing | Local | Available | `data/forcing/Data_forcing_03hr_010deg/` |
| MSWX forcing | Local | Available | `KISSPATH_FORCING/` |
| CaMa-Flood output | From pipeline | Available | `model/cmf_v420_pkg/out/` |
| AVHRR land cover | Local | Available | `data/forcing/AVHRR/` |

---

## Quick Start

```bash
# Activate venv
source KISSPATH_PYTHON_ENV/bin/activate

# 1. Define domain (from existing basin shapefile)
python tools/s1_domain/setup_sfincs_domain.py \
  --shp_path data/shp/chaohe_shp/chaohe.shp \
  --resolution 100 \
  --output_dir outputs/sfincs_test/

# 2. Build topography (auto-selects China DEM)
python tools/s2_topobathy/build_sfincs_topobathy.py \
  --grid_info outputs/sfincs_test/grid_info.json \
  --shp_path data/shp/chaohe_shp/chaohe.shp \
  --output_dir outputs/sfincs_test/

# 3. Build roughness
python tools/s3_roughness/build_sfincs_roughness.py \
  --grid_info outputs/sfincs_test/grid_info.json \
  --uniform_n 0.04 \
  --output_dir outputs/sfincs_test/

# 4. Prepare rainfall forcing
python tools/s4_forcing/prepare_sfincs_rainfall.py \
  --forcing_dir outputs/chaohe_run/vic_temp/forcing/forcing_final \
  --grid_info outputs/sfincs_test/grid_info.json \
  --start_date 2003-07-01 --end_date 2003-09-30 \
  --source vic_ascii \
  --output_dir outputs/sfincs_test/

# 5. Generate configuration
python tools/s6_config/generate_sfincs_inp.py \
  --grid_info outputs/sfincs_test/grid_info.json \
  --start_date 20030701 --end_date 20030930 \
  --precip_file outputs/sfincs_test/sfincs.precip \
  --output_dir outputs/sfincs_test/

# 6. Run SFINCS
python tools/s7_execution/run_sfincs.py \
  --run_dir outputs/sfincs_test/

# 7. Extract and plot results
python tools/s8_postprocess/extract_sfincs_results.py \
  --map_nc outputs/sfincs_test/sfincs_map.nc \
  --grid_info outputs/sfincs_test/grid_info.json \
  --output_dir outputs/sfincs_test/results/

python tools/s8_postprocess/plot_sfincs_flood_map.py \
  --flood_depth outputs/sfincs_test/results/flood_max_depth.npy \
  --grid_info outputs/sfincs_test/grid_info.json \
  --title "Chaohe Flood Inundation July-Sep 2003" \
  --output outputs/sfincs_test/flood_map.png
```

---

## Diagnostic Triplets

26 triplets covering 8 failure domains. See `diagnostics/triplets.yaml` for full details.

### Original triplets (dt_001 to dt_020) — from dissection

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | **silent** | unit_conversion | Precip mm/3hr not divided by 3 (flood 3x too deep) |
| dt_002 | **silent** | unit_conversion | Precip in m/s instead of mm/hr (no flooding) |
| dt_003 | **silent** | unit_conversion | Discharge mm/day not converted to m3/s |
| dt_004 | **silent** | unit_conversion | Vertical datum EGM96 vs MSL offset 20-40m |
| dt_005 | fatal | spatial_error | CRS mismatch: geographic deg with metric dx/dy |
| dt_006 | **silent** | spatial_error | Grid origin mismatch after reprojection |
| dt_007 | **silent** | spatial_error | Edge cells mask=3 instead of mask=2 (no outflow) |
| dt_008 | degraded | spatial_error | Subgrid ratio > 30x causes checkerboard |
| dt_009 | fatal | timestep | CFL violation: dt > dx/sqrt(g*h) -> NaN crash |
| dt_010 | degraded | timestep | Advection + low alpha -> oscillations |
| dt_011 | degraded | timestep | Grid too fine -> 100x runtime |
| dt_012 | **silent** | boundary | Bnd point on inactive mask cell -> ignored |
| dt_013 | degraded | boundary | Source point on hilltop -> artificial pond |
| dt_014 | **silent** | coupling | Double-counted precipitation (VIC + SFINCS) |
| dt_015 | **silent** | coupling | CaMa discharge sign -> reverse flow |
| dt_016 | degraded | coupling | Daily CaMa BC -> artificial 24hr ramps |
| dt_017 | fatal | io_path | Binary not run from CWD containing sfincs.inp |
| dt_018 | degraded | io_path | outputformat missing -> binary not NetCDF |
| dt_019 | **silent** | io_path | Mask all zeros -> output all zeros |
| dt_020 | fatal | parameter | Manning's n < 0.01 -> CFL instability |

### Validated triplets (dt_v001 to dt_v006) — from Chaohe basin test

| ID | Severity | Domain | Summary | Error Log |
|----|----------|--------|---------|-----------|
| dt_v001 | **fatal** | file_format | sfincs.ind binary format wrong (full 2D grid vs header+indices) | err_006 |
| dt_v002 | **fatal** | unit_conversion | VIC forcing col 0 is temp, not precip — wrong column read | err_007 |
| dt_v003 | **fatal** | temporal_alignment | Multi-year VIC forcing time offset not computed | err_008 |
| dt_v004 | degraded | file_format | NetCDF precip via netprecipfile silently fails — use ASCII | err_009 |
| dt_v005 | **silent** | boundary_condition | mask=2 drains inland terrain at 0m water level | err_010 |
| dt_v006 | degraded | runtime | gfortran SIGABRT after "Simulation finished" — output valid | err_004 |

### Validated triplets (dt_v007 to dt_v008) — from Bengbu flood test

| ID | Severity | Domain | Summary | Error Log |
|----|----------|--------|---------|-----------|
| dt_v007 | **silent** | variable_selection | extract_sfincs_results used `zsmax` (water surface elevation) instead of `hmax` (water depth) — flood depths 310m instead of 7m | err_011 |
| dt_v008 | **silent** | config_generation | generate_sfincs_inp wrote `netprecipfile` but ASCII precip needs `precipfile` — silently falls back to no precipitation | err_012 |

### Validated triplets (dt_v016 to dt_v020) — from the Kangerlussuaq / Watson River test (2026-08-02)

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_v016 | **fatal** | environment | Venv netCDF4 1.7.4 / HDF5 1.14.6 cannot open ANY SFINCS output ("NetCDF: HDF error"); ncdump/GDAL/h5py/h5netcdf can — s8 was dead server-wide. Fallback to `engine="h5netcdf"` |
| dt_v017 | **silent** | postprocess | `hmax = +9999` fill outside the mask survived the negative-only clip — reported max flood depth 9999 m |
| dt_v018 | **fatal** | io_path | `--source mswx` globbed `*prec*` + `YYYYMM`, which never matches MSWX's annual `P/P_YYYY.nc` — MSWX forcing could never load |
| dt_v019 | **silent** | boundary_condition | s2 set EVERY edge cell to mask=2; on a mixed coast+upland domain the upland edges (held at zs=0) drain everything. Added `--min_elev` / `--outflow_max_elev` |
| dt_v020 | degraded | timestep | s6 hard-coded `h_max = 10 m` for the CFL dt regardless of bathymetry; now derived from `topobathy_summary.json` |

> **`triplets.yaml` was invalid YAML until 2026-08-02.** `dt_v009`–`dt_v015` were
> indented 2 spaces, making them children of `dt_v008`'s mapping, so `yaml.safe_load`
> raised `expected <block end>, but found '-'` and **no** triplet was programmatically
> loadable. De-indented; the file now parses to 40 entries.

**Total**: 28 triplets. **Silent error count**: 13/28 (46%). **Validated from real runs**: 8/28 (29%).

---

## File Structure

```
models/SFINCS/knowledge_infrastructure/
  DISSECTION_PLAN.md              # Original dissection plan
  SKILL.md                        # This file (agent entry point)
  knowledge_infrastructure.yaml   # Schema-compliant package definition
  tools/
    s1_domain/
      setup_sfincs_domain.py      # Grid from shapefile/bbox
    s2_topobathy/
      build_sfincs_topobathy.py   # DEM to sfincs.dep/msk/ind
    s3_roughness/
      build_sfincs_roughness.py   # Manning's n from land cover
    s4_forcing/
      prepare_sfincs_rainfall.py  # CMFD/MSWX to sfincs.precip (mm/hr)
      cama_to_sfincs_boundary.py  # CaMa-Flood to sfincs.src/.dis or .bnd/.bzs
    s5_structures/
      (future: setup_sfincs_structures.py)
    s6_config/
      generate_sfincs_inp.py      # Generate sfincs.inp with CFL dt
    s7_execution/
      run_sfincs.py               # Execute with preflight checks
    s8_postprocess/
      extract_sfincs_results.py   # Parse sfincs_map.nc, flood stats
      plot_sfincs_flood_map.py    # Flood depth map visualization
  docs/
    s1_domain_skill.md ... s8_postprocess_skill.md
  diagnostics/
    triplets.yaml                 # 26 diagnostic triplets (20 from dissection + 6 from Chaohe validation)
    error_log.yaml                # 10 error log entries (6 promoted to triplets)

model/sfincs/
  bin/sfincs                      # SFINCS v2.3.2 binary (compiled from source, validated)
  bin/VERSION                     # Build metadata
  compile_sfincs.sh               # Compilation script (for rebuilding)
```
