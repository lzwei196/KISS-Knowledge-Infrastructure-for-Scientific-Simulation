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

---

# CaMa-Flood v4.20 -- River Routing and Floodplain Model

CaMa-Flood (Catchment-based Macro-scale Floodplain model) is a global-scale river routing model that simulates river discharge, water depth, and floodplain inundation from gridded runoff input. It is the **coupling backbone** between land surface/hydrological models (VIC, wflow, HYPE) and local flood models (SFINCS).

## Key Paths

| Component | Path |
|-----------|------|
| Binary | `/mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/src/MAIN_cmf` |
| Source code | `/mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/src/` |
| Global river map (15min) | `/mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/map/glb_15min/` |
| Regional maps | `/mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/map/{basin}_15min/` |
| Run scripts | `/mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/gosh/` |
| Output directory | `/mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/out/` |
| Runoff climatology data | `/mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/map/data/ELSE_GPCC_coastmod_dayclm-1981-2010.one` |
| KI tools | `/mnt/disk1/Hydrocraft_server/models/CaMa_Flood/knowledge_infrastructure/tools/` |
| Diagnostics | `/mnt/disk1/Hydrocraft_server/models/CaMa_Flood/knowledge_infrastructure/diagnostics/triplets.yaml` |

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
                            Output: CSV time series, spatial summaries
```

---

## Data Preparation

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

## Output Variables

| Variable | File Pattern | Units | Description |
|----------|-------------|-------|-------------|
| outflw | o_outflw{YYYY}.nc | m3/s | River discharge (primary validation) |
| rivdph | o_rivdph{YYYY}.nc | m | River channel water depth |
| sfcelv | o_sfcelv{YYYY}.nc | m ASL | Water surface elevation |
| flddph | o_flddph{YYYY}.nc | m | Floodplain inundation depth |
| fldfrc | o_fldfrc{YYYY}.nc | 0-1 | Floodplain inundation fraction |
| rivsto | o_rivsto{YYYY}.nc | m3 | River channel storage volume |

---

## Critical Domain Knowledge

### 1. Absolute Paths Are Mandatory (dt_cama_001)

CaMa-Flood resolves file paths relative to the current working directory at runtime. Since run scripts `cd` to the output directory before executing, relative paths (`../../map/...`) break unpredictably. **Always use absolute paths** for ALL file references in the namelist: CDIMINFO, CNEXTXY, CGRAREA, CELEVTN, CNXTDST, CRIVLEN, CFLDHGT, CRIVWTH, CRIVHGT, CRIVMAN, CINPMAT, CROFCDF.

### 2. calc_outclm Must Run from glb_15min (dt_cama_004)

The climatological mean discharge computation needs the FULL global river network topology to accumulate runoff correctly. Running it from a regional directory produces zero or incorrect outclm.bin, leading to wrong channel widths. **Always run calc_outclm from map/glb_15min/, then copy outclm.bin to the regional directory.**

### 3. calc_rivwth Must Use Regional diminfo (dt_cama_003, dt_cama_008)

After copying outclm.bin from glb_15min, run calc_rivwth in the regional directory using the **regional** diminfo file. Using the global diminfo produces oversized binary files with garbage values. This is a known bug in setup_cama_basin.py.

### 4. Inpmat Grid Must Match VIC Grid, Not CaMa Domain (dt_cama_002)

The WESTIN/EASTIN/NORTHIN/SOUTHIN parameters in inpmat generation describe the **source runoff grid** (VIC/wflow), NOT the CaMa domain. Confusing these produces near-zero discharge everywhere.

### 5. Latitude Order: North-to-South (dt_cama_007)

CaMa-Flood expects runoff NetCDF with latitude in **descending** order (north to south). The OLAT parameter in inpmat generation must match. Mismatch causes every CaMa cell to map to wrong VIC cells.

### 6. Spin-Up for Stable Initial Conditions

First-year results are unreliable due to empty initial river storage. Always run 1-2 spin-up iterations of the first year (restart the first year using its own end-of-year state). The run scripts handle this with the NSP/SPINUP logic.

### 7. PMANRIV Is the Primary Calibration Parameter

Manning's roughness for river channels (PMANRIV) is the main calibration lever:
- Default: 0.03 (typical for natural rivers)
- Bengbu calibrated: 0.30 (much higher -- reflects channel complexity at 15min resolution)
- Higher values slow flow, increasing peak attenuation and lag time

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

---

## Validated Results

### Bengbu (Huai River), VIC-coupled

- **Period**: 2000-2005 (2 spin-up years on 2000)
- **Resolution**: 15min CaMa, 0.25 deg VIC
- **Manning's n**: PMANRIV=0.30, PMANFLD=0.10
- **NSE**: 0.598 (daily discharge at Bengbu station)
- **Peak discharge**: ~6900 m3/s (2003 flood)
- **Output location**: `/mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/out/bengbu_2000_2005_cama/`

---

## Usage Examples

### Example 1: Full pipeline for a new basin

```bash
# 0. Preflight
cd /mnt/disk1/Hydrocraft_server/models/CaMa_Flood/knowledge_infrastructure
python preflight_check.py

# 1. Prepare runoff from VIC output
python tools/prepare_runoff_input.py \
    --source vic \
    --input_dir /mnt/disk1/Hydrocraft_server/outputs/bengbu_2000_2005/vic_result \
    --output_dir /mnt/disk1/Hydrocraft_server/outputs/bengbu_2000_2005_cama/cama_input \
    --basin_name bengbu \
    --start_year 2000 --end_year 2005 \
    --file_prefix "huaihe_fluxes_"

# 2. Configure simulation (map prep + run script)
python tools/configure_simulation.py \
    --basin_name bengbu \
    --west 111.75 --east 117.75 --south 31.0 --north 35.0 \
    --grid_resolution 0.25 \
    --start_year 2000 --end_year 2005 \
    --runoff_dir /mnt/disk1/Hydrocraft_server/outputs/bengbu_2000_2005_cama/cama_input \
    --runoff_prefix "bengbu_runoff_1d_"

# 3. Execute
python tools/run_cama.py \
    --script /mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh

# 4. Parse output
python tools/parse_cama_output.py \
    --output_dir /mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/out/bengbu_2000_2005_cama \
    --variable outflw \
    --lat 32.95 --lon 117.35 \
    --start_year 2000 --end_year 2005
```

### Example 2: Quick re-run with different Manning's n

Edit the run script and change PMANRIV:
```bash
cd /mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/gosh
# Change PMANRIV in run_bengbu_1d_nc.sh from 0.30D0 to 0.05D0
# Then re-run
python /mnt/disk1/Hydrocraft_server/models/CaMa_Flood/knowledge_infrastructure/tools/run_cama.py \
    --script run_bengbu_1d_nc.sh
```

---

## References

- CaMa-Flood official: http://hydro.iis.u-tokyo.ac.jp/~yamadai/cama-flood/
- CaMa-Flood v4 GitHub: https://github.com/global-hydrodynamics/CaMa-Flood_v4
- Manual: `model/cmf_v420_pkg/doc/Manual_CaMa-Flood_v420.docx`
- Yamazaki et al. (2011): A physically based description of floodplain inundation dynamics in a global river routing model. Water Resources Research.
