# Channel Routing and Stream Threshold — Skill Document

> **Stage ID**: s4_channel_routing
> **Pipeline order**: 4 of 12 (part of Fulldom construction + namelist configuration)
> **Depends on**: s1_domain, s2_geo_em, s4_fulldom, s9_namelists

## Purpose

WRF-Hydro's channel routing transports water from hillslopes through a stream network to the basin outlet. The channel network is defined by thresholding flow accumulation on the routing grid, and discharge is computed using either diffusive wave or Muskingum-Cunge methods. The stream threshold — which determines how many cells become channels — is the single most critical routing configuration decision: too high and you get zero channels (dt_v016), too low and every cell is a channel (unrealistic). This document covers channel routing physics, stream threshold selection (including the `smart_stream_threshold()` auto-scaling function), overland flow parameters, channel parameter tables, and correct discharge extraction from output files.

## Prerequisites

Before configuring channel routing, verify:

- [ ] `Fulldom_hires.nc` exists in DOMAIN/ with FLOWDIRECTION, TOPOGRAPHY variables
- [ ] `domain_def.json` exists with grid dimensions and projection parameters
- [ ] Basin shapefile is available for basin mask rasterization
- [ ] DEM has been reprojected to the routing LCC grid
- [ ] D8 flow directions have been converted from WhiteboxTools to ArcGIS encoding (dt_v007)
- [ ] Boundary flow directions are set to 0 (dt_001)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| `Fulldom_hires.nc` | file | s4_fulldom | Routing domain with FLOWDIRECTION, FLOWACC |
| `stream_threshold` | integer | User or auto | Flow accumulation threshold for channel definition |
| `channel_option` | integer (1-3) | hydro.namelist | Routing physics method |
| `CHANPARM.TBL` | lookup table | WRF-Hydro distribution | Manning's N and channel width per stream order |
| `OVROUGHRTFAC` | float | Fulldom_hires.nc | Overland roughness scaling factor |
| `RETDEPRTFAC` | float | Fulldom_hires.nc | Retention depth scaling factor |
| `DXRT` | float (m) | hydro.namelist | Routing grid spacing |
| `DTRT_CH` | integer (s) | hydro.namelist | Channel routing timestep |
| `DTRT_TER` | integer (s) | hydro.namelist | Terrain (overland) routing timestep |

## Procedure

Follow these steps in exact order. Do not skip, reorder, or improvise.

### Step 1: Understand Channel Routing Physics

WRF-Hydro provides three channel routing methods, selected via `channel_option` in `hydro.namelist`:

#### channel_option = 3: Diffusive Wave (DEFAULT for gridded routing)

**How it works**: Solves the diffusive wave approximation of the Saint-Venant equations on the channel grid. Water flows downstream through cells connected by the D8 flow direction network. At each timestep, flow between cells is computed using Manning's equation with a diffusion term that dampens flood wave propagation.

**Key equations (plain language)**:
- Flow velocity: V = (1/n) * R^(2/3) * S^(1/2) (Manning's equation)
- Discharge: Q = V * A (velocity x cross-sectional area)
- Diffusion term smooths the wave as it propagates downstream
- Channel geometry: trapezoidal cross-section with width `Bw` from CHANPARM.TBL per Strahler order

**Strengths**: Physically realistic wave propagation and attenuation; handles backwater effects; stable for most configurations.

**Limitations**: Requires sufficiently small DTRT_CH to satisfy CFL condition (dt_013). Cannot handle supercritical flow.

#### channel_option = 1: Muskingum-Cunge (reach-based, type 1)

**How it works**: Uses the Muskingum-Cunge method — a hydrologic routing technique that approximates diffusive wave routing using reach storage relationships. Requires reach definitions (typically from NHDPlus or similar).

**When to use**: When reach-based routing (NHDPlus) is configured with UDMP_OPT=1. Not applicable to gridded routing.

#### channel_option = 2: Muskingum-Cunge (reach-based, type 2)

Similar to option 1 with different parameter handling. Also requires reach-based setup.

**Recommendation**: For gridded routing (the standard HydroCraft pipeline), always use **channel_option = 3** (diffusive wave).

### Step 2: Understand Stream Threshold Methods

The stream threshold determines which routing grid cells become channels. Three approaches:

#### Method A: NCAR Default (Fixed Cell Count)

Threshold = 200 cells (hardcoded in many NCAR examples).

**Problem**: Does not scale with resolution or basin size.
- At 250m routing (1km LSM, AGGFACTRT=4): works for medium basins (>5000 km2)
- At 7km routing (0.25deg, AGGFACTRT=4): basin with 170 routing cells gets ZERO channels because max(FLOWACC)=86 < 200 (dt_v016)
- At 100m routing: 200 is too few — produces only low-order streams

#### Method B: USGS Flow-Based (1 cfs Threshold)

Channel exists where mean accumulated runoff >= 1 cubic foot per second (0.028 m3/s).

**How it works**:
1. Estimate mean annual runoff using Budyko: `runoff_ratio = f(P, PET)`
2. Convert to runoff rate: `runoff_m_s = P * runoff_ratio / (365.25 * 86400)`
3. Compute accumulated flow per cell: `Q_cell = FLOWACC * cell_area * runoff_m_s`
4. Threshold = number of cells needed for Q_cell >= 0.028 m3/s

**Problem**: At coarse routing grids (>=500m), every cell exceeds 1 cfs (all become channels).

#### Method C: Auto-Scaling (`smart_stream_threshold()`) — RECOMMENDED

The `build_fulldom_hires.py` tool includes `smart_stream_threshold()` which automatically selects the appropriate method:

```python
def smart_stream_threshold(cell_area_m2, basin_cells, precip_mm_yr=800, temp_mean_c=15):
    cell_size = sqrt(cell_area_m2)
    # Budyko runoff ratio
    runoff_ratio = max(0.05, 1 - (1 + aridity - (1 + aridity**2)**0.5))

    if cell_size < 500:
        # Fine grid: USGS flow-based (1 cfs = 0.028 m3/s)
        cells_for_1cfs = 0.028 / (cell_area * runoff_m_s)
        threshold = max(5, int(cells_for_1cfs))
    else:
        # Coarse grid: scale-aware (2% of basin, max 200, min 5)
        threshold = max(5, min(200, int(basin_cells * 0.02)))
    return threshold, runoff_ratio
```

**Usage**:
```bash
python tools/s4_fulldom/build_fulldom_hires.py \
  --stream_threshold 0 \   # 0 = auto (smart_stream_threshold)
  ...
```

Pass `--stream_threshold 0` (auto) or omit to use the auto method. Pass a positive integer to override.

**Expected result**: `build_fulldom_hires.py` prints the computed threshold and number of channel cells.

**If this fails**: See dt_v016 (zero channels) or dt_v021 (threshold doesn't scale).

### Step 3: Verify Channel Network

After `build_fulldom_hires.py` creates Fulldom_hires.nc, verify the channel network:

```python
import netCDF4 as nc
import numpy as np

ds = nc.Dataset("DOMAIN/Fulldom_hires.nc")
channelgrid = ds["CHANNELGRID"][:]
streamorder = ds["STREAMORDER"][:]
ds.close()

n_channel = int((channelgrid == 0).sum())    # WRF-Hydro: 0 = channel
n_total = channelgrid.size
max_order = int(streamorder.max())

print(f"Channel cells: {n_channel} / {n_total} ({100*n_channel/n_total:.1f}%)")
print(f"Max Strahler order: {max_order}")
```

**Expected values**:
| Metric | Acceptable Range | Warning |
|--------|-----------------|---------|
| Channel fraction | 1-10% of routing cells | <0.5% = too few, >20% = too many |
| Max Strahler order | 3-7 for basins >1000 km2 | <3 = insufficient network |
| Channel cells | >20 for any basin | 0 = fatal (dt_v016) |

**If channel cells = 0**: Threshold exceeds max(FLOWACC). Reduce threshold or use auto.

### Step 4: Configure Overland Flow Parameters

Overland flow (hillslope to channel) is controlled by two factors in Fulldom_hires.nc:

#### OVROUGHRTFAC (Overland Roughness Factor)

- Default: 1.0
- Effect: Multiplies the overland roughness from HYDRO.TBL. Higher = slower overland flow = delayed peaks.
- Range: 0.1 (fast, sharp peaks) to 10.0 (slow, dampened peaks)
- **Calibration use**: Tier 2 — adjust after REFKDT to fine-tune peak timing

#### RETDEPRTFAC (Retention Depth Factor)

- Default: 1.0
- Effect: Controls surface ponding/retention. Higher = more water ponded on surface before flowing = dampened peaks.
- Range: 0.1 (minimal ponding) to 10.0 (significant ponding)
- **Calibration use**: Tier 2 — adjust to dampen peak overshoot

To modify:
```python
import netCDF4 as nc

ds = nc.Dataset("DOMAIN/Fulldom_hires.nc", "a")
ds["OVROUGHRTFAC"][:] = 1.0   # Adjust as needed
ds["RETDEPRTFAC"][:] = 1.0    # Adjust as needed
ds.close()
```

### Step 5: Understand Channel Parameters (CHANPARM.TBL)

Manning's N and bottom width (Bw) are assigned per Strahler stream order from `CHANPARM.TBL`:

| Order | MannN | Bw (m) | Description |
|-------|-------|--------|-------------|
| 1 | 0.09-0.10 | 1.5-3 | First-order headwater streams |
| 2 | 0.06-0.08 | 3-8 | Small tributaries |
| 3 | 0.05-0.06 | 8-20 | Medium tributaries |
| 4 | 0.04-0.05 | 20-50 | Main tributaries |
| 5 | 0.03-0.04 | 50-100 | Major rivers |
| 6+ | 0.02-0.03 | 100-300 | Large rivers |

**Calibration**: Multiply all MannN values by a factor (0.5-3.0) to shift peak timing:
- Higher MannN = slower flow = later, lower peaks
- Lower MannN = faster flow = earlier, higher peaks

### Step 6: Configure Routing Timesteps (CFL Compliance)

In `hydro.namelist`:

```fortran
DXRT = 250.0        ! Routing grid spacing (meters)
DTRT_CH = 10         ! Channel routing timestep (seconds)
DTRT_TER = 10        ! Terrain routing timestep (seconds)
```

**CFL condition**: `DTRT < DXRT / V_max`. For typical max velocities ~5 m/s:
- DXRT=250m: DTRT <= 50s (use 10s for safety)
- DXRT=1000m: DTRT <= 200s (use 10-30s)
- DXRT=7000m: DTRT <= 1400s (use 60-300s)

**If CFL is violated**: Model crashes with segmentation fault or NaN values (dt_013).

### Step 7: Extract Discharge Correctly — CHRTOUT vs LDASOUT

**THIS IS CRITICAL. Get this wrong and your discharge is 2-3x overestimated.**

#### CHRTOUT (Channel Routing Output) — USE THIS

- File pattern: `*.CHRTOUT_DOMAIN1`
- Key variables: `streamflow` (m3/s), `q_lateral` (m3/s), `velocity` (m/s)
- One value per channel cell (1D array indexed by `feature_id`)
- **Units**: m3/s — direct, no conversion needed
- **How to find the outlet**: Select the feature_id with the highest mean streamflow, or the channel cell closest to the basin outlet coordinates

```python
import netCDF4 as nc
import numpy as np
import glob

files = sorted(glob.glob("*.CHRTOUT_DOMAIN1"))
discharge = []
for f in files:
    ds = nc.Dataset(f)
    q = ds["streamflow"][:]
    discharge.append(float(q.max()))  # Outlet = max streamflow
    ds.close()
```

#### LDASOUT (Land Surface Output) — DO NOT USE FOR DISCHARGE

- File pattern: `*.LDASOUT_DOMAIN1`
- Contains `SFCRNOFF` and `UGDRNOFF` — but these are **accumulated** values that **include routed upstream flow** when overland/subsurface routing is enabled (OVRTSWCRT=1, SUBRTSWCRT=1)
- Basin-averaging SFCRNOFF gives **2.4x overestimate** of actual discharge (dt_v009)
- Headwater cells: Q/P = 0.35-0.38 (correct local runoff)
- Channel cells: Q/P = 0.96 (includes upstream contributions — NOT local runoff)

**NEVER compute basin discharge by averaging SFCRNOFF from LDASOUT. ALWAYS use CHRTOUT.**

### Step 8: Comparison with VIC Routing

| Feature | WRF-Hydro Channel Routing | VIC + Lohmann Routing | VIC + CaMa-Flood |
|---------|--------------------------|----------------------|------------------|
| Method | Diffusive wave on grid | Unit hydrograph convolution | Kinematic/diffusive wave |
| Channel definition | Explicit D8 channels from DEM | Not needed (impulse response) | Global river network |
| Timestep | Seconds (DTRT_CH) | Daily | Minutes |
| Floodplain | No | No | Yes (river-floodplain exchange) |
| Backwater | Limited (diffusive wave) | No | Yes |
| Setup complexity | DEM -> D8 -> threshold -> channels | Flow direction file + station file | Map regionalization + inpmat |
| **Why VIC doesn't need channels** | N/A | VIC uses a linearized unit hydrograph: each cell's runoff is convolved with an impulse response function (IRF) derived from flow distance and velocity, then summed at the outlet. No explicit channel network is needed — the routing is purely mathematical. | CaMa-Flood has its own global channel network |

## Expected Outputs

After successful completion, the following should exist:

| Output | Path | Verification |
|--------|------|--------------|
| Fulldom_hires.nc with channels | `DOMAIN/Fulldom_hires.nc` | `CHANNELGRID` has values 0 (channel) and -9999 (non-channel) |
| CHRTOUT files | `<run_dir>/*.CHRTOUT_DOMAIN1` | Contains `streamflow` variable with non-zero values |
| Channel network | Fulldom_hires.nc `STREAMORDER` | Max order >= 3 for basins > 1000 km2 |

## Validation Checks

Run these checks before proceeding to the next stage:

1. **Channel cell count**: Verify sufficient channels exist
   - Command: `python -c "import netCDF4 as nc; ds=nc.Dataset('DOMAIN/Fulldom_hires.nc'); print('Channel cells:', (ds['CHANNELGRID'][:]==0).sum())"`
   - Expected: >20 for any basin, 1-10% of total routing cells
   - If zero: Threshold too high (dt_v016). Use `--stream_threshold 0` (auto).
   - If unexpected: See diagnostic triplet dt_v016

2. **CHANNELGRID encoding**: Verify correct encoding
   - Command: `python -c "import netCDF4 as nc; ds=nc.Dataset('DOMAIN/Fulldom_hires.nc'); cg=ds['CHANNELGRID'][:]; print('Unique values:', set(cg.flatten().tolist()[:10]))"`
   - Expected: Only values 0 (channel) and -9999 (non-channel)
   - If 0 and 1: Wrong encoding (dt_v010). Must be -9999/0, not 0/1.

3. **CHRTOUT has non-zero discharge**: After a test run
   - Command: `python -c "import netCDF4 as nc; ds=nc.Dataset('<latest_CHRTOUT>'); print('Max Q:', ds['streamflow'][:].max(), 'm3/s')"`
   - Expected: >0 m3/s during rain events
   - If zero everywhere: AGGFACTRT mismatch (dt_014) or no surface runoff (dt_v018)

4. **CFL stability**: No NaN in streamflow
   - Command: `python -c "import netCDF4 as nc, numpy as np; ds=nc.Dataset('<latest_CHRTOUT>'); print('NaN count:', np.isnan(ds['streamflow'][:]).sum())"`
   - Expected: 0
   - If NaN present: Reduce DTRT_CH (dt_013)

## Common Pitfalls

> **PITFALL**: Using LDASOUT SFCRNOFF for basin discharge
> This happens when users average SFCRNOFF across all grid cells to compute basin discharge. The symptom is discharge 2-3x higher than observations or VIC comparison.
> **Do this instead**: Extract discharge from CHRTOUT files at the outlet feature_id. SFCRNOFF includes routed upstream flow and is NOT local runoff when routing is enabled.
> See diagnostic triplet dt_v009 for full details.

> **PITFALL**: Fixed stream threshold across resolutions
> This happens when using threshold=200 (NCAR default) at coarse resolution. The symptom is zero channel cells, zero discharge in CHRTOUT, and GW bucket-dominated flow with inverted seasonal cycle (dt_v017).
> **Do this instead**: Use `--stream_threshold 0` (auto) which calls `smart_stream_threshold()`, or manually set threshold to `max(5, basin_routing_cells * 0.02)` for coarse grids.
> See diagnostic triplets dt_v016, dt_v021 for full details.

> **PITFALL**: CHANNELGRID encoding inverted (0/1 instead of -9999/0)
> This happens when building Fulldom_hires.nc with standard binary encoding. The symptom is all non-channel cells treated as channels and actual channels ignored — routing topology is completely wrong, producing zero or nonsensical discharge.
> **Do this instead**: Ensure CHANNELGRID uses WRF-Hydro convention: 0=channel, -9999=non-channel. The updated `build_fulldom_hires.py` handles this correctly.
> See diagnostic triplet dt_v010 for full details.

> **PITFALL**: AGGFACTRT mismatch between Fulldom and wrfinput
> This happens when hydro.namelist AGGFACTRT does not match the actual ratio of Fulldom dimensions to wrfinput dimensions. The symptom is zero discharge in CHRTOUT despite non-zero runoff in LDASOUT.
> **Do this instead**: Set AGGFACTRT = Fulldom_x_dim / wrfinput_x_dim. `generate_namelists.py` auto-detects this.
> See diagnostic triplet dt_014 for full details.

> **PITFALL**: Channel threshold sensitivity testing without fixing land surface runoff first
> This happens when users try many threshold values (5, 10, 20, 50, 170) but all give the same discharge. The symptom is that channel configuration has no impact on discharge magnitude.
> **Do this instead**: First verify that Noah-MP is producing sufficient surface runoff (check SFCRNOFF in LDASOUT). If surface runoff is near zero (REFKDT too high), the channel network has nothing to route — fix REFKDT first, then tune channel parameters.
> See diagnostic triplet dt_v018 (err_025) for full details.

---

*This skill document is part of the `hydrocraft-wrfhydro-standalone` knowledge infrastructure.*
*Stage s4 of 12 | Tools used: build_fulldom_hires, generate_namelists | Related triplets: dt_001, dt_v007, dt_v009, dt_v010, dt_v016, dt_v017, dt_v021, dt_013, dt_014*
