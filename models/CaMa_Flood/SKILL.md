---
name: cama-flood-integration
description: CaMa-Flood v4.20 river routing and floodplain model. Routes gridded runoff (from VIC, wflow, HYPE, etc.) through a global river network to produce discharge, water depth, and flood inundation extent.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Task
---

> **MANDATORY EXECUTION POLICY** -- READ BEFORE PROCEEDING
>
> You MUST run the **actual CaMa-Flood Fortran binary** (`MAIN_cmf`) described in this document.
> If the model fails to compile or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python routing formula, Muskingum equation,
> or hand-coded approximation in place of the real CaMa-Flood binary. Doing so
> produces scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (6 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (10 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (37 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (20 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-20 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/calib_run.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help` |
| `tools/configure_simulation.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/configure_simulation.py --help` |
| `tools/gfd_flood_obs.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/gfd_flood_obs.py --help` |
| `tools/parse_cama_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_cama_output.py --help` |
| `tools/prepare_runoff_input.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/prepare_runoff_input.py --help` |
| `tools/run_cama.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_cama.py --help` |

*6 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

# CaMa-Flood v4.20 -- River Routing and Floodplain Model

CaMa-Flood (Catchment-based Macro-scale Floodplain model) is a global-scale river routing model that simulates river discharge, water depth, and floodplain inundation from gridded runoff input. It is the **coupling backbone** between land surface/hydrological models (VIC, wflow, HYPE) and local flood models (SFINCS).

## Key Paths

| Component | Path |
|-----------|------|
| Binary | `KISSPATH_BINARIES/cmf_v420_pkg/src/MAIN_cmf` |
| Source code | `KISSPATH_BINARIES/cmf_v420_pkg/src/` |
| Global river map (15min) | `KISSPATH_BINARIES/cmf_v420_pkg/map/glb_15min/` |
| Regional maps | `KISSPATH_BINARIES/cmf_v420_pkg/map/{basin}_15min/` |
| Run scripts | `KISSPATH_BINARIES/cmf_v420_pkg/gosh/` |
| Output directory | `KISSPATH_BINARIES/cmf_v420_pkg/out/` |
| Runoff climatology data | `KISSPATH_BINARIES/cmf_v420_pkg/map/data/ELSE_GPCC_coastmod_dayclm-1981-2010.one` |
| KI tools | `KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure/tools/` |
| Diagnostics | `KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure/diagnostics/triplets.yaml` |

---

## Pipeline Overview

```
Stage 0: Preflight         python preflight_check.py
                           |
Stage 1: Prepare runoff    tools/prepare_runoff_input.py
         (VIC/wflow/HYPE   Converts model output -> CaMa NetCDF
          -> NetCDF)        Output: {basin}_runoff_1d_YYYY.nc
                           |
Stage 2: Configure basin   tools/configure_simulation.py
         (map preparation)  Step 2.1: Regionalize (cut_domain from glb_15min)
                            Step 2.2: Generate inpmat (VIC grid -> CaMa grid)
                            Step 2.3: Channel parameters (calc_outclm + calc_rivwth)
                            Step 2.4: Generate run script
                            Output: map/{basin}_15min/ with all .bin files
                           |
Stage 3: Execute           tools/run_cama.py
                            Runs MAIN_cmf via generated shell script
                            Handles spin-up, restart, yearly loops
                            Output: o_outflw{YYYY}.nc, o_flddph{YYYY}.nc, etc.
                           |
Stage 4: Post-process      tools/parse_cama_output.py
                            Extract discharge at gauge points
                            Compute flood statistics
                            Reduce a variable over a date window to a 2-D field (--field)
                            Reads BOTH output forms: o_{var}{YYYY}.nc and {var}{YYYY}.bin
                            Output: CSV time series, spatial summaries, field NetCDF
                           |
Stage 5: Flood extent      tools/downscale/run_downscale.sh   (15min -> 1min/30sec/...)
         (ONLY for         tools/gfd_flood_obs.py             (GFD v1.4 observation)
          fldfrc/fldare)    Output: flood_{YYYYMMDD}.bin, aggregated obs NetCDF
```

### Validating flood extent (`fldfrc`, `fldare`) against GFD

`docs/validation_convention.yaml` (fldfrc / spatial_snapshot, determining metric **csi**,
Bernhofen 2018 bands: satisfactory 0.5 / good 0.6 / very good 0.7) requires the sub-grid
fraction to be **downscaled to the native high-resolution grid before wet/dry thresholding**.
The raw 0.25° `fldfrc` is NOT comparable to a 250 m satellite mask. The working chain is:

```bash
# 1. the run MUST emit binary output -- the official downscaler cannot read o_*.nc
python tools/configure_simulation.py ... --output_format binary \
       --output_vars 'outflw,rivout,rivdph,rivvel,sfcelv,flddph,fldfrc,fldare,rivsto'

# 2. downscale flddph with CaMa's own downscale_flddph_trib
bash tools/downscale/run_downscale.sh --map_dir <map> --out_dir <out> \
     --syear 2001 --smon 8 --eyear 2001 --emon 11 --res 1min \
     --west 98 --east 109.5 --south 8.5 --north 21.75 --dest <dest>

# 3. build the observation on the SAME grid
python tools/gfd_flood_obs.py --event_id 1781 \
     --west 98 --east 109.5 --south 8.5 --north 21.75 \
     --resolution 0.0166666666666667 --out_nc gfd_1781_1min.nc
```

Three traps that silently destroy CSI (**dt_cama_015**):
1. **Permanent water.** GFD's `flooded` band EXCLUDES JRC permanent water; the downscaler
   FORCES every `<res>.rivwth.bin` pixel to `max(0.1, depth)`. Drop permanent-water pixels
   (`gfd_flood_obs.py` does by default) and threshold the model **strictly above 0.1 m**.
2. **Reduction.** GFD band 1 is a composite MAXIMUM extent over the whole event window — so
   reduce the model with `max` over the same window, never sample one day.
3. **Cloud / footprint.** GFD is NaN outside the observed footprint and MODIS cannot see
   through cloud (`clear_views`, `clear_perc`). Require a minimum observed fraction per cell.

Pick the window as a multiple of BOTH the target resolution and 0.25°, at least 1.25° inside
the map domain (the downscaler adds a 5-grid buffer), and confirm the raster footprint from
the GeoTIFF's own bounds rather than the DFO centroid.

### Stage Skill Documents

- [Stage 0: Preflight skill](docs/s0_preflight_skill.md)
- [Stage 1: Prepare runoff skill](docs/s1_prepare_runoff_skill.md)
- [Stage 2: Configure basin skill](docs/s2_configure_basin_skill.md)
- [Stage 3: Execute CaMa-Flood skill](docs/s3_execute_cama_skill.md)
- [Stage 4: Post-process output skill](docs/s4_postprocess_skill.md)

---

## Data Preparation

**Data Validation Reference**: See `data_ki/ObservedQ/SKILL.md` for observed discharge validation data.
See `data_ki/ChinaDEM/SKILL.md` for DEM and river network data.


### Input Runoff Requirements

CaMa-Flood accepts gridded runoff on a regular lat/lon grid as NetCDF:
- **Variable name**: `Runoff` (capital R)
- **Units**: mm/day (CaMa-Flood converts internally to m3/s using grid area)
- **Dimensions**: `(time, lat, lon)`
- **Latitude order**: North-to-South (descending) -- this is critical; see dt_cama_007
- **Grid resolution**: Typically 0.25 deg (matching VIC/wflow)
- **Time step**: Daily (IFRQ_INP=24 hours)

### Data KI Adapters

| Source Model | Adapter | Key Conversion |
|-------------|---------|----------------|
| VIC 5.1 | `tools/prepare_runoff_input.py --source vic` | OUT_RUNOFF + OUT_BASEFLOW -> Runoff (mm/day) |
| wflow_sbm | `tools/prepare_runoff_input.py --source wflow` | Lateral runoff extraction (avoid double-counting routed Q) |
| HYPE | `tools/prepare_runoff_input.py --source hype` | cout.txt total runoff -> gridded NetCDF |
| Generic NC | `tools/prepare_runoff_input.py --source netcdf` | Variable rename + unit conversion |

### CRITICAL: Unit Mismatches (dt_cama_009)

VIC outputs runoff in **mm/day**. CaMa-Flood expects **mm/day** in the NetCDF. Do NOT convert to m3/s before feeding to CaMa -- the model handles the area-weighted conversion internally using ctmare.bin (catchment area).

If you accidentally provide m3/s, discharge will be off by orders of magnitude (typically 1e6 too high for large basins).

---

## Map Preparation (Three Mandatory Steps)

**CRITICAL WARNING**: Every new basin requires fresh map preparation. NEVER reuse map files from another basin (dt_cama_005). The three steps MUST be executed in order.

### Step 1: Regionalization (cut from global map)

Extracts a regional sub-domain from the global 15-minute river network.

```bash
# Directory: map/{basin}_15min/src_region/
# Inputs: region_info.txt with SOURCE, WEST, EAST, SOUTH, NORTH
# Tools: cut_domain, cut_bifway, set_map, combine_hires
# Output: nextxy.bin, ctmare.bin, elevtn.bin, nxtdst.bin, rivlen.bin,
#         fldhgt.bin, width.bin, 1min/ (high-res for downscaling)
```

The `configure_simulation.py` tool automates this step. If running manually:

1. Create the map directory: `mkdir -p map/{basin}_15min/src_region`
2. Copy tools from glb_15min: `cp -r map/glb_15min/src_region/* map/{basin}_15min/src_region/`
3. **Recompile** (binaries are platform-specific): `cd map/{basin}_15min/src_region && make clean && make all`
4. Edit `s01-regional_map.sh` with basin bounds (add buffer of ~0.5 deg)
5. Run: `./s01-regional_map.sh`

### Step 2: Input Matrix Generation (VIC grid -> CaMa grid mapping)

Creates the spatial mapping between the source runoff grid and the CaMa river network.

```bash
# Directory: map/{basin}_15min/src_param/
# Inputs: VIC grid extent (WESTIN, EASTIN, NORTHIN, SOUTHIN), grid resolution
# Tools: generate_inpmat
# Output: diminfo_{basin}_025deg.txt, inpmat_{basin}_025deg.bin
```

**CRITICAL**: WESTIN/EASTIN/NORTHIN/SOUTHIN must match the **VIC grid extent**, NOT the CaMa domain extent (dt_cama_002). Use cell edge coordinates (center +/- half resolution).

### Step 3: Channel Parameters (width, depth, Manning's n)

Derives river channel geometry from climatological mean discharge.

```bash
# Must run calc_outclm from glb_15min/ (needs global river network, dt_cama_004)
# Then run calc_rivwth from the REGIONAL directory with REGIONAL diminfo (dt_cama_003/008)
# Output: rivwth.bin, rivhgt.bin, rivwth_gwdlr.bin, rivman.bin, outclm.bin
```

Default channel parameter coefficients:
- Width: W = WC * Q^WP, WC=2.50, WP=0.60, WMIN=5.0 m
- Depth: H = HC * Q^HP, HC=0.10, HP=0.50, HMIN=1.0 m
- Manning's n: 0.03 (river), 0.10 (floodplain)

---

## Namelist Configuration (input_cmf.nam)

The CaMa-Flood binary reads configuration from a Fortran namelist file. Key sections:

### &NRUNVER -- Run version control
| Parameter | Default | Description |
|-----------|---------|-------------|
| LADPSTP | .TRUE. | Enable adaptive time stepping |
| LPTHOUT | .FALSE. | Path-based output (off for standard runs) |
| LRESTART | .FALSE. | Restart from previous state (set .TRUE. for year > 1) |

### &NDIMTIME -- Grid and time
| Parameter | Example | Description |
|-----------|---------|-------------|
| CDIMINFO | `'/mnt/.../diminfo_bengbu_025deg.txt'` | **Absolute path** to dimension info file |
| DT | 86400 | Base time step in seconds (daily) |
| IFRQ_INP | 24 | Input frequency in hours |

### &NPARAM -- Physical parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| PMANRIV | 0.03D0 | Manning's n for river channel (calibration param) |
| PMANFLD | 0.10D0 | Manning's n for floodplain |
| PCADP | 0.7 | CFL condition coefficient for adaptive time step |
| PDSTMTH | 10000.D0 | Distance threshold for diffusion wave (m) |

### &NSIMTIME -- Simulation period
| Parameter | Example | Description |
|-----------|---------|-------------|
| SYEAR/SMON/SDAY/SHOUR | 2000/1/1/0 | Simulation start |
| EYEAR/EMON/EDAY/EHOUR | 2001/1/1/0 | Simulation end (exclusive) |

### &NMAP -- River network files (ALL must use absolute paths)
| Parameter | File | Description |
|-----------|------|-------------|
| LMAPCDF | .FALSE. | Use binary map files (not NetCDF) |
| CNEXTXY | nextxy.bin | Flow direction (downstream cell indices) |
| CGRAREA | ctmare.bin | Catchment area per cell (m2) |
| CELEVTN | elevtn.bin | Elevation (m) |
| CNXTDST | nxtdst.bin | Distance to downstream cell (m) |
| CRIVLEN | rivlen.bin | River channel length (m) |
| CFLDHGT | fldhgt.bin | Floodplain height profile (m) |
| CRIVWTH | rivwth_gwdlr.bin | River channel width (m) |
| CRIVHGT | rivhgt.bin | River channel depth (m) |
| CRIVMAN | rivman.bin | Manning's n spatial field |

### &NFORCE -- Forcing input
| Parameter | Example | Description |
|-----------|---------|-------------|
| LINPCDF | .TRUE. | Input is NetCDF format |
| LINTERP | .TRUE. | Use input matrix for grid mapping |
| CINPMAT | `'.../inpmat_bengbu_025deg.bin'` | Input matrix file (absolute path) |
| CROFCDF | `'.../bengbu_runoff_1d_2003.nc'` | Runoff NetCDF file (absolute path) |
| CVNROF | 'Runoff' | Variable name in NetCDF (capital R) |

### &NOUTPUT -- Output control
| Parameter | Example | Description |
|-----------|---------|-------------|
| COUTDIR | './' | Output directory (relative OK, run script cd's here) |
| CVARSOUT | 'outflw,rivdph,sfcelv,flddph,fldfrc' | Comma-separated output variables |
| COUTTAG | '2003' | Year tag for output filenames |
| LOUTCDF | .TRUE. | Output as NetCDF (.FALSE. for binary) |
| IFRQ_OUT | 24 | Output frequency in hours |

---

## 6. Output Description

This section restates `dag.yaml`; if the body and dag ever disagree, `dag.yaml` wins.

**Headline output** (`validation_rank: 1`):

> `outflw` -- Total main-river-network discharge (river outflow + floodplain outflow + bifurcation outflow); primary validation variable. (`m3/s`)

Other dag-declared outputs: `rivout`, `rivdph`, `sfcelv`, `flddph`, `fldfrc`, `fldare`, `rivvel`, `rivsto`.

| Variable | File Pattern | Units | Description |
|----------|-------------|-------|-------------|
| outflw | o_outflw{YYYY}.nc | m3/s | Total main-river-network discharge (river outflow + floodplain outflow + bifurcation outflow); primary validation variable. |
| rivout | o_rivout{YYYY}.nc | see `dag.yaml` | Dag-declared output; use `dag.yaml` for the authoritative unit and description. |
| rivdph | o_rivdph{YYYY}.nc | m | River channel water depth |
| sfcelv | o_sfcelv{YYYY}.nc | m ASL | Water surface elevation |
| flddph | o_flddph{YYYY}.nc | m | Floodplain inundation depth |
| fldfrc | o_fldfrc{YYYY}.nc | 0-1 | Floodplain inundation fraction |
| fldare | o_fldare{YYYY}.nc | see `dag.yaml` | Dag-declared output; use `dag.yaml` for the authoritative unit and description. |
| rivvel | o_rivvel{YYYY}.nc | see `dag.yaml` | Dag-declared output; use `dag.yaml` for the authoritative unit and description. |
| rivsto | o_rivsto{YYYY}.nc | m3 | River channel storage volume |

## 8. Unit Conversion Table

This table records the body-level unit contract for input preparation and post-processing. For output variables, `dag.yaml` is authoritative.

| Variable | Source unit (verified) | Model unit / output unit | Factor | Type | Notes |
|----------|------------------------|--------------------------|--------|------|-------|
| Runoff | mm/day | mm/day | x1 | passthrough | CaMa-Flood expects `Runoff` in mm/day and converts internally to m3/s using catchment area. |
| OUT_RUNOFF + OUT_BASEFLOW (VIC adapter) | mm/day | Runoff, mm/day | x1 after summing | additive | `tools/prepare_runoff_input.py --source vic` maps VIC runoff components to CaMa `Runoff`. |
| outflw | model output | m3/s | x1 | output unit | Dag rank-1 output unit is `m3/s`. Do not pre-convert runoff to m3/s before CaMa-Flood. |

---

## Critical Domain Knowledge

### 1. Absolute Paths Are Mandatory (dt_cama_001)

CaMa-Flood resolves file paths relative to the current working directory at runtime. Since run scripts `cd` to the output directory before executing, relative paths (`../../map/...`) break unpredictably. **Always use absolute paths** for ALL file references in the namelist: CDIMINFO, CNEXTXY, CGRAREA, CELEVTN, CNXTDST, CRIVLEN, CFLDHGT, CRIVWTH, CRIVHGT, CRIVMAN, CINPMAT, CROFCDF.

### 2. calc_outclm Must Run from glb_15min (dt_cama_004)

The climatological mean discharge computation needs the FULL global river network topology to accumulate runoff correctly. Running it from a regional directory produces zero or incorrect outclm.bin, leading to wrong channel widths. **Always run calc_outclm from map/glb_15min/ — then CLIP its output to the regional domain. NEVER raw-copy it.**

⚠️ **DO NOT `cp` / `shutil.copy2` the global outclm.bin into the regional map dir** (this SKILL and the KI tool both used to say "copy", and that instruction is what produced the bug). calc_outclm writes a GLOBAL-sized array (1440×720); calc_rivwth reads the regional file with fixed-recl direct access sized to the REGIONAL nx·ny, so a raw copy hands it a meaningless byte slice and channel width/depth collapse to the WMIN/HMIN floors (2.0 m / 1.0 m) basin-wide. Measured 2026-08-19: 40 of 43 regional maps on this server had rivhgt.bin pinned at 1.0 m from exactly this. Use `tools/configure_simulation.py` (its `_clip_global_outclm()` does it correctly), and note the byte order — calc_rivwth declares `rivout(nx,ny)` (index = ix + iy·nx, Fortran order) while numpy's `tofile()` writes C order, so the clip MUST be written with `.ravel(order='F')` or correct values land on the WRONG cells. See triplet **dt_cama_012**.

### 3. calc_rivwth Must Use Regional diminfo (dt_cama_003, dt_cama_008)

After CLIPPING outclm.bin from glb_15min (never copying — see above), run calc_rivwth in the regional directory using the **regional** diminfo file. Using the global diminfo produces oversized binary files with garbage values. Both the raw-copy and the global-diminfo variants of this bug were live in `skills/cama-flood-run/setup_cama_basin.py` and in this KI's own `tools/configure_simulation.py`; both were fixed on 2026-08-19/20, and `setup_cama_basin.py` now refuses to continue if the resulting geometry is not downstream-consistent (channel width must correlate with drainage area).

### 4. Inpmat Grid Must Match VIC Grid, Not CaMa Domain (dt_cama_002)

The WESTIN/EASTIN/NORTHIN/SOUTHIN parameters in inpmat generation describe the **source runoff grid** (VIC/wflow), NOT the CaMa domain. Confusing these produces near-zero discharge everywhere.

### 5. Latitude Order: North-to-South (dt_cama_007)

CaMa-Flood expects runoff NetCDF with latitude in **descending** order (north to south). The OLAT parameter in inpmat generation must match. Mismatch causes every CaMa cell to map to wrong VIC cells.

### 6. Spin-Up for Stable Initial Conditions

First-year results are unreliable due to empty initial river storage. Always run 1-2 spin-up iterations of the first year (restart the first year using its own end-of-year state). The run scripts handle this with the NSP/SPINUP logic.

### 7. PMANRIV Is the Primary Calibration Parameter

Manning's roughness for river channels (PMANRIV) is the main calibration lever:
- Default: 0.03 (typical for natural rivers)
- Bengbu calibrated: 0.30 -- **SUSPECT, re-check before reuse** (see below)
- Higher values slow flow, increasing peak attenuation and lag time

**CHANNEL DEPTH IS THE OTHER (UNDOCUMENTED) KNOB — CHECK IT BEFORE CALIBRATING PMANRIV.**
`rivhgt.bin` (CRIVHGT) is NOT observed data and is NOT shipped in the official CaMa map archives
or in MERIT Hydro — riverbed depth cannot be measured from space. It is DERIVED per basin as
`H = max(Hmin, Hc * Qave^Hp)` from the discharge climatology (outclm.bin), with Hc set at setup
time. The global map here was built with Hc=0.10 (CaMa convention); our
`skills/cama-flood-run/setup_cama_basin.py` defaults to `--hc 0.50`, i.e. 5x deeper channels, with
no recorded justification. Width has a real-data path (GWD-LR `width.bin` via set_gwdlr); depth
has none, so a bad discharge climatology silently floors it at Hmin.

Consequence measured 2026-08-19: 40 of 43 regional maps on this server had `rivhgt.bin` pinned at
1.0 m everywhere (triplet dt_cama_012). A PMANRIV calibrated on floor-value channels is a COMPENSATING
error — 0.30 is ~10x the physical value for a natural river, which is what you would expect if
roughness were absorbing channels that are far too shallow. Before trusting or transferring any
PMANRIV, verify the geometry first (dt_cama_012 detection command), then decide Hc against observed
discharge/stage rather than inheriting a default.

---

## Error Handling

Consult `diagnostics/triplets.yaml` for structured symptom-diagnosis-remedy lookup. Key errors:

| Error | Triplet | Quick Fix |
|-------|---------|-----------|
| STOP 10 (immediate exit) | dt_cama_001 | Use absolute paths in namelist |
| Near-zero discharge | dt_cama_002 | Fix inpmat WESTIN/EASTIN to match VIC grid |
| Wrong channel widths | dt_cama_003/008 | Re-run calc_rivwth with regional diminfo |
| calc_outclm fails | dt_cama_004 | Run from glb_15min/, not regional dir |
| Wrong river network | dt_cama_005 | Regenerate map for this specific basin |
| Padded zeros in input | dt_cama_006 | Trim NetCDF to actual VIC grid extent |
| Lat ordering mismatch | dt_cama_007 | Check OLAT vs NC lat direction |
| Unit mismatch (mm/day vs m3/s) | dt_cama_009 | Keep mm/day; CaMa converts internally |
| diminfo format error | dt_cama_010 | Check integer/float formatting in diminfo |
| Missing 1min directory | dt_cama_011 | Re-run regionalization with combine_hires |
| `NetCDF: HDF error` opening a file `ncdump` reads fine | dt_cama_014 | xarray's DEFAULT engine is broken in this python_env; the tools' `open_nc()` falls back to `h5netcdf`. Never conclude the file is corrupt. |
| Flood-extent CSI near zero, false alarms along every river | dt_cama_015 | Downscale first, drop permanent water, threshold **above** 0.1 m |
| Downscaling errors with a `/Volumes/...` path | dt_cama_016 | Use `tools/downscale/run_downscale.sh` (the other two scripts in that dir are still dead macOS symlinks) |

---

## 11. Validated Results

### Bengbu (Huai River), VIC-coupled

- **Period**: 2000-2005 (2 spin-up years on 2000)
- **Resolution**: 15min CaMa, 0.25 deg VIC
- **Manning's n**: PMANRIV=0.30, PMANFLD=0.10
- **NSE**: 0.598 (daily discharge at Bengbu station)
- **Peak discharge**: ~6900 m3/s (2003 flood)
- **Output location**: `KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/`

### Performance Metrics -- judged against the field's bar

The bar below restates `docs/validation_convention.yaml`; if this body and the convention file ever disagree, `docs/validation_convention.yaml` wins. A band held as null in the convention must be written as `no cited threshold`, not guessed.

| Dag variable | Metric | Direction | Satisfactory band | Good band | Very good band |
|--------------|--------|-----------|-------------------|-----------|----------------|
| outflw | nse | maximize | >= 0.5 (moriasi2007, moriasi2015) | >= 0.65 (moriasi2007, moriasi2015) | >= 0.75 (moriasi2007, moriasi2015) |
| outflw | pbias | zero_centered | <= 25 (moriasi2007, moriasi2015) | <= 15 (moriasi2007, moriasi2015) | <= 10 (moriasi2007, moriasi2015) |
| outflw | pbias | zero_centered | <= 25 (moriasi2007) | <= 15 (moriasi2007) | <= 10 (moriasi2007) |
| sfcelv | nse | maximize | >= 0.5 (moriasi2007, revel2023) | >= 0.65 (moriasi2007, revel2023) | >= 0.75 (moriasi2007, revel2023) |

| Metric | Calibration | Validation | Full Period | Bar (convention, cited) |
|--------|-------------|------------|-------------|-------------------------|
| NSE for `outflw` | not reported here | not reported here | 0.598 | satisfactory >= 0.5 (moriasi2007, moriasi2015); good >= 0.65 (moriasi2007, moriasi2015); very good >= 0.75 (moriasi2007, moriasi2015) |
| PBIAS for `outflw` | not reported here | not reported here | not reported here | satisfactory <= 25 (moriasi2007, moriasi2015); good <= 15 (moriasi2007, moriasi2015); very good <= 10 (moriasi2007, moriasi2015) |
| NSE for `sfcelv` | not reported here | not reported here | not reported here | satisfactory >= 0.5 (moriasi2007, revel2023); good >= 0.65 (moriasi2007, revel2023); very good >= 0.75 (moriasi2007, revel2023) |

---

## Usage Examples

### Example 1: Full pipeline for a new basin

```bash
# 0. Preflight
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python preflight_check.py

# 1. Prepare runoff from VIC output
python tools/prepare_runoff_input.py \
    --source vic \
    --input_dir KISSPATH_OUTPUTS/bengbu_2000_2005/vic_result \
    --output_dir KISSPATH_OUTPUTS/bengbu_2000_2005_cama/cama_input \
    --basin_name bengbu \
    --start_year 2000 --end_year 2005 \
    --file_prefix "huaihe_fluxes_"

# 2. Configure simulation (map prep + run script)
python tools/configure_simulation.py \
    --basin_name bengbu \
    --west 111.75 --east 117.75 --south 31.0 --north 35.0 \
    --grid_resolution 0.25 \
    --start_year 2000 --end_year 2005 \
    --runoff_dir KISSPATH_OUTPUTS/bengbu_2000_2005_cama/cama_input \
    --runoff_prefix "bengbu_runoff_1d_"

# 3. Execute
python tools/run_cama.py \
    --script KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh

# 4. Parse output
python tools/parse_cama_output.py \
    --output_dir KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama \
    --variable outflw \
    --lat 32.95 --lon 117.35 \
    --start_year 2000 --end_year 2005
```

### Example 2: Quick re-run with different Manning's n

Edit the run script and change PMANRIV:
```bash
cd KISSPATH_BINARIES/cmf_v420_pkg/gosh
# Change PMANRIV in run_bengbu_1d_nc.sh from 0.30D0 to 0.05D0
# Then re-run
python KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure/tools/run_cama.py \
    --script run_bengbu_1d_nc.sh
```

---

## References

- CaMa-Flood official: http://hydro.iis.u-tokyo.ac.jp/~yamadai/cama-flood/
- CaMa-Flood v4 GitHub: https://github.com/global-hydrodynamics/CaMa-Flood_v4
- Manual: `model/cmf_v420_pkg/doc/Manual_CaMa-Flood_v420.docx`
- Yamazaki et al. (2011): A physically based description of floodplain inundation dynamics in a global river routing model. Water Resources Research.


## Stage documentation (one doc per pipeline stage)

- docs/s0_preflight.md
- docs/s0_preflight_skill.md
- docs/s1_prepare_runoff.md
- docs/s1_prepare_runoff_skill.md
- docs/s2_configure_basin.md
- docs/s2_configure_basin_skill.md
- docs/s3_execute_cama.md
- docs/s3_execute_cama_skill.md
- docs/s4_postprocess.md
- docs/s4_postprocess_skill.md
