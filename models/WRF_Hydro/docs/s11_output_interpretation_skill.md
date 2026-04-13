# WRF-Hydro Output Interpretation -- Skill Document

> **Stage ID**: s11_output_interpretation
> **Pipeline order**: 11 of 12 (post-execution analysis)
> **Depends on**: s10_execution (completed WRF-Hydro run)

## Purpose

WRF-Hydro produces four distinct output file types (LDASOUT, CHRTOUT, RTOUT, GWOUT) plus forcing input files (LDASIN), each containing different variables at different spatial scales and with different semantics. Misinterpreting which file to use for which purpose is one of the most common and costly WRF-Hydro errors. Specifically, using basin-averaged SFCRNOFF from LDASOUT for discharge gives a 2.4x overestimate (dt_v009), and failing to set RESTART_FREQUENCY_HOURS correctly causes zero output files to be written (dt_015). This document covers all output file types, correct discharge extraction, water balance verification, and the relationship between output variables.

## Prerequisites

Before interpreting output, verify:

- [ ] WRF-Hydro run completed successfully ("The model finished successfully" in stdout)
- [ ] `CHRTOUT_DOMAIN = 1` was set in hydro.namelist (required for discharge)
- [ ] `RESTART_FREQUENCY_HOURS` was set to -9999 or a positive integer in namelist.hrldas (not 0)
- [ ] Spinup period identified (first 6-12 months to discard)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| `*.LDASOUT_DOMAIN1` | NetCDF files | WRF-Hydro run | Land surface output (LSM grid) |
| `*.CHRTOUT_DOMAIN1` | NetCDF files | WRF-Hydro run | Channel routing output (1D channel cells) |
| `*.RTOUT_DOMAIN1` | NetCDF files | WRF-Hydro run | Routing grid output (high-res, optional) |
| `*.GWOUT_DOMAIN1` | NetCDF files | WRF-Hydro run | Groundwater bucket output |
| `*.LDASIN_DOMAIN1` | NetCDF files | s8_forcing | Forcing input (for verification) |
| `Fulldom_hires.nc` | NetCDF | DOMAIN/ | Channel cell locations (for outlet identification) |
| Basin shapefile | file | data/shp/ | For masking basin cells |

## Procedure

Follow these steps in exact order. Do not skip, reorder, or improvise.

### Step 1: Verify Output Files Exist

```python
import glob

ldasout = sorted(glob.glob("*.LDASOUT_DOMAIN1"))
chrtout = sorted(glob.glob("*.CHRTOUT_DOMAIN1"))
gwout   = sorted(glob.glob("*.GWOUT_DOMAIN1"))
rtout   = sorted(glob.glob("*.RTOUT_DOMAIN1"))

print(f"LDASOUT: {len(ldasout)} files")
print(f"CHRTOUT: {len(chrtout)} files")
print(f"GWOUT:   {len(gwout)} files")
print(f"RTOUT:   {len(rtout)} files")
```

**Expected**: LDASOUT and CHRTOUT should have >= 1 file per output timestep (e.g., 365 for 1 year at daily output). If LDASOUT count is 0 but CHRTOUT exists, RESTART_FREQUENCY_HOURS was set to 0 (dt_015).

**If CHRTOUT is empty or missing**: CHRTOUT_DOMAIN was set to 0 in hydro.namelist. Re-run with `CHRTOUT_DOMAIN = 1`.

### Step 2: Understand Each Output File Type

---

#### LDASOUT (Land Surface Output)

**File pattern**: `YYYYMMDD00.LDASOUT_DOMAIN1`
**Grid**: LSM grid (coarse, e.g., 22x18 at 0.25deg or 126x116 at 1km)
**Frequency**: Every `RESTART_FREQUENCY_HOURS` (set -9999 for every OUTPUT_TIMESTEP)

**Key variables**:

| Variable | Units | Description | Notes |
|----------|-------|-------------|-------|
| **SFCRNOFF** | mm | Surface runoff (accumulated) | **WARNING: includes routed upstream flow when OVRTSWCRT=1** (dt_v009) |
| **UGDRNOFF** | mm | Subsurface drainage to GW bucket | Recharge TO bucket, not baseflow FROM it |
| SOIL_M(1-4) | m3/m3 | Volumetric soil moisture per layer | 4 layers: 0-10, 10-40, 40-100, 100-200 cm |
| TSLB(1-4) | K | Soil temperature per layer | Check for NaN (dt_009) |
| SNEQV | kg/m2 | Snow water equivalent | = mm water equivalent |
| CANWAT | kg/m2 | Canopy water content | Interception store |
| ETRAN | mm | Transpiration | Component of total ET |
| EDIR | mm | Direct soil evaporation | Component of total ET |
| ECAN | mm | Canopy evaporation | Component of total ET |
| LH | W/m2 | Latent heat flux | ET = LH / 2.5e6 (mm/s) |
| HFX | W/m2 | Sensible heat flux | Energy balance check |
| FSA | W/m2 | Net shortwave absorbed | Should be < SWDOWN |
| FIRA | W/m2 | Net longwave radiation | Typically negative (surface emits) |
| GRDFLX | W/m2 | Ground heat flux | Small compared to LH, HFX |
| ACSNOM | mm | Accumulated snowmelt | Cumulative |

**CRITICAL WARNING on SFCRNOFF (dt_v009)**:

When overland routing is enabled (`OVRTSWCRT=1` in hydro.namelist, which is the default), LDASOUT SFCRNOFF at each cell includes:

1. Local surface runoff generated at that cell (correct), PLUS
2. Routed surface flow arriving from ALL upstream cells (wrong for basin averaging)

This means:
- **Headwater cells** (no upstream contributors): SFCRNOFF represents true local runoff. Typical Q/P ratio = 0.35-0.38.
- **Channel cells** (many upstream contributors): SFCRNOFF is inflated by all upstream water flowing through. Typical Q/P ratio = 0.96.
- **Basin-averaged SFCRNOFF**: Gives **2.4x overestimate** of actual basin discharge because the same water is counted multiple times as it flows from cell to cell.

**NEVER compute basin discharge as**: `discharge = mean(SFCRNOFF) * basin_area / dt`

**How to compute daily increments from LDASOUT accumulated fields**:

SFCRNOFF and UGDRNOFF are accumulated since model start. To get per-timestep values:
```python
import netCDF4 as nc
import numpy as np

files = sorted(glob.glob("*.LDASOUT_DOMAIN1"))

for i in range(1, len(files)):
    ds_curr = nc.Dataset(files[i])
    ds_prev = nc.Dataset(files[i-1])

    sfcrnoff_increment = ds_curr['SFCRNOFF'][0] - ds_prev['SFCRNOFF'][0]
    ugdrnoff_increment = ds_curr['UGDRNOFF'][0] - ds_prev['UGDRNOFF'][0]

    ds_curr.close()
    ds_prev.close()
```

**Note**: For headwater-only analysis (e.g., comparing Noah-MP runoff generation with VIC), mask to only headwater cells (no upstream channels).

**Masking basin cells vs domain average**:

The LSM grid covers a rectangular domain larger than the basin. To compute basin-specific statistics, mask using LANDMASK or the rasterized basin:

```python
import netCDF4 as nc

ds_geo = nc.Dataset("DOMAIN/geo_em.d01.nc")
landmask = ds_geo['LANDMASK'][0]  # 1=land, 0=water
ds_geo.close()

ds_out = nc.Dataset("YYYYMMDD00.LDASOUT_DOMAIN1")
soil_m = ds_out['SOIL_M'][0, 0]  # Layer 1
basin_mean = float(np.nanmean(soil_m[landmask > 0.5]))
ds_out.close()
```

---

#### CHRTOUT (Channel Routing Output) -- USE THIS FOR DISCHARGE

**File pattern**: `YYYYMMDD00.CHRTOUT_DOMAIN1`
**Grid**: 1D array of channel cells (indexed by `feature_id`)
**Frequency**: Every `out_dt` minutes (from hydro.namelist)

**Key variables**:

| Variable | Units | Description | Notes |
|----------|-------|-------------|-------|
| **streamflow** | **m3/s** | **Routed discharge at each channel cell** | **This is what to use for discharge comparison** |
| q_lateral | m3/s | Lateral inflow from hillslope to channel | Local runoff contribution |
| velocity | m/s | Flow velocity in channel | For routing validation |
| Head | m | Water surface elevation | For flood analysis |
| order | - | Strahler stream order | For identifying outlet |

**Units are m3/s -- no conversion needed.** This is the correct and only source for basin discharge.

**How to find the outlet feature (Step-by-step)**:

```python
import netCDF4 as nc
import numpy as np
import glob

files = sorted(glob.glob("*.CHRTOUT_DOMAIN1"))

# Method 1: Feature with highest cumulative streamflow (RECOMMENDED)
q_total = None
for f in files:
    ds = nc.Dataset(f)
    q = ds["streamflow"][:]
    if q_total is None:
        q_total = np.zeros_like(q)
    q_total += np.abs(q)
    ds.close()

outlet_idx = int(np.argmax(q_total))
print(f"Outlet feature index: {outlet_idx}")
print(f"Outlet mean Q: {q_total[outlet_idx] / len(files):.1f} m3/s")

# Method 2: Highest Strahler order (backup)
ds = nc.Dataset(files[0])
if 'order' in ds.variables:
    orders = ds['order'][:]
    outlet_idx = int(np.argmax(orders))
ds.close()
```

**Extracting daily discharge timeseries**:

```python
import netCDF4 as nc
import numpy as np
import glob
from datetime import datetime

files = sorted(glob.glob("*.CHRTOUT_DOMAIN1"))
dates = []
discharge = []

for f in files:
    # Parse date from filename
    basename = f.split("/")[-1]
    datestr = basename[:8]  # YYYYMMDD
    dates.append(datetime.strptime(datestr, "%Y%m%d"))

    ds = nc.Dataset(f)
    q = ds["streamflow"][:]
    discharge.append(float(q[outlet_idx]))
    ds.close()

# dates[] and discharge[] are now aligned daily timeseries
print(f"Period: {dates[0].date()} to {dates[-1].date()}")
print(f"Mean Q: {np.mean(discharge):.1f} m3/s")
print(f"Peak Q: {np.max(discharge):.1f} m3/s")
```

---

#### GWOUT (Groundwater Bucket Output)

**File pattern**: `YYYYMMDD00.GWOUT_DOMAIN1`
**Grid**: Per GW basin (typically 1D, one value per basin ID)
**Frequency**: Same as LDASOUT (RESTART_FREQUENCY_HOURS)

**Key variables**:

| Variable | Units | Description | Notes |
|----------|-------|-------------|-------|
| z_gwsubbas | mm | Water depth in GW bucket | Conceptual, not physical water table |
| qin_gwsubbas | m3/s | Inflow to bucket (deep drainage recharge) | Input from Noah-MP UGDRNOFF |
| qout_gwsubbas | m3/s | Outflow from bucket (baseflow to channels) | This IS the baseflow component |
| qloss_gwsubbas | m3/s | Deep percolation loss | Water lost below bucket bottom |

**Common confusion**: LDASOUT UGDRNOFF is drainage TO the bucket (recharge). GWOUT qout_gwsubbas is drainage FROM the bucket (baseflow). They are different quantities with different timing.

---

#### RTOUT (Routing Grid Output -- Optional)

**File pattern**: `YYYYMMDD00.RTOUT_DOMAIN1`
**Grid**: High-resolution routing grid (e.g., 88x72 at routing resolution)
**Enabled by**: `RTOUT_DOMAIN = 1` in hydro.namelist (disabled by default)

| Variable | Units | Description | Notes |
|----------|-------|-------------|-------|
| sfcheadsubrt | m | Surface water depth on routing grid | For flood depth mapping |
| zwattablrt | m | Water table depth | Spatial groundwater analysis |
| QSTRMVOLRT | m3 | Streamflow volume per cell | Spatial flow distribution |
| QBDRYRT | m3 | Boundary flux | Domain boundary check |

**Warning**: RTOUT files can be very large for high-resolution domains (e.g., 2140x1768 routing grid = 3.8M cells). Only enable when spatial flood analysis is needed.

---

#### LDASIN (Forcing Input -- for Verification)

**File pattern**: `YYYYMMDDHH.LDASIN_DOMAIN1`
**Grid**: LSM grid
**Frequency**: Hourly (FORCING_TIMESTEP=3600)

Use LDASIN to verify forcing data is correct:

| Variable | Expected Range | If Wrong |
|----------|---------------|----------|
| T2D | 230-330 K | Check unit conversion (dt_v008) |
| RAINRATE | 0-0.01 mm/s (normal), 0-0.05 (extreme) | If > 0.1: division by 10800 missed (dt_011) |
| PSFC | 50000-110000 Pa | If < 1000: kPa not converted to Pa |
| SWDOWN | 0-1200 W/m2 (0 at night) | If > 1361: cap at solar constant (dt_017) |
| LWDOWN | 100-500 W/m2 | Should never be 0 or negative |
| Q2D | 0.001-0.025 kg/kg | If > 0.1: kPa not converted (dt_012) |
| U2D, V2D | -30 to 30 m/s | Should be decomposed from scalar wind |

### Step 3: Discard Spinup Period (dt_v014)

Cold-start runs produce unrealistic output for the first 6-12 months:

**Day 1 symptoms**:
- SFCRNOFF = 237 mm/day (extreme, physically impossible)
- Soil moisture: starts at field capacity everywhere, not representative of actual spatial patterns
- Snow: starts at zero, needs a full winter to accumulate correctly
- GW bucket: starts at Zinit, needs months to reach equilibrium

**Rule**: Always discard the first 6-12 months of output before any analysis or comparison with observations.

**Alternative**: Do a separate 1-year spinup run, save the RESTART file at the end, then use that RESTART file for the analysis run (set `RESTART_FILE` in hydro.namelist and `GW_RESTART = 1`).

### Step 4: Extract and Compare Discharge

**Correct method** (CHRTOUT):

```python
# Extract from CHRTOUT at outlet (see Step 2 above)
# Units: m3/s directly, no conversion needed
q_wrfhydro = [...]  # from CHRTOUT streamflow at outlet_idx
```

**For comparison with VIC**:

| WRF-Hydro Variable | VIC Equivalent | Unit Conversion |
|--------------------|----------------|-----------------|
| CHRTOUT `streamflow` (m3/s) | Lohmann/CaMa outlet Q (m3/s) | None -- both m3/s |
| LDASOUT `LH` (W/m2) | `OUT_EVAP` (mm) | WRF: ET_mm = LH / 2.5e6 * dt |
| LDASOUT `SOIL_M` (m3/m3) | `OUT_SOIL_MOIST` (mm) | WRF: mm = SOIL_M * layer_depth_mm |
| LDASOUT `SNEQV` (kg/m2) | `OUT_SWE` (mm) | 1 kg/m2 = 1 mm |
| GWOUT `qout_gwsubbas` (m3/s) | `OUT_BASEFLOW` (mm) | VIC: convert mm to m3/s using area |

**Expected magnitude differences** (uncalibrated, from Bengbu comparison):
- WRF-Hydro / VIC discharge ratio: ~0.71 (WRF-Hydro 29% lower with default params)
- Daily timing correlation r: ~0.84
- Best single-year r: 0.92 (2003)
- These differences are expected with different physics (Noah-MP vs VIC, Schaake vs ARNO infiltration)

### Step 5: Water Balance Verification

For any completed run, verify mass balance closure:

```python
import netCDF4 as nc
import numpy as np
import glob

# Sum over entire run (post-spinup)
files = sorted(glob.glob("*.LDASOUT_DOMAIN1"))

# Get first and last file
ds_first = nc.Dataset(files[0])
ds_last  = nc.Dataset(files[-1])

# Accumulated variables (difference = total over period)
total_sfcrnoff = ds_last['SFCRNOFF'][0] - ds_first['SFCRNOFF'][0]  # mm
total_ugdrnoff = ds_last['UGDRNOFF'][0] - ds_first['UGDRNOFF'][0]  # mm

# Storage change
soil_m_start = sum(ds_first[f'SOIL_M'][0, layer] * depth
                   for layer, depth in enumerate([100, 300, 600, 1000]))  # mm
soil_m_end   = sum(ds_last[f'SOIL_M'][0, layer] * depth
                   for layer, depth in enumerate([100, 300, 600, 1000]))
delta_s = soil_m_end - soil_m_start  # mm

ds_first.close()
ds_last.close()

# From LDASIN: total precipitation
ldasin_files = sorted(glob.glob("*.LDASIN_DOMAIN1"))
total_precip = 0
for f in ldasin_files:
    ds = nc.Dataset(f)
    total_precip += ds['RAINRATE'][0].mean() * 3600  # mm per hour
    ds.close()

# Balance: P = ET + Q + delta_S
# (Q from CHRTOUT, not SFCRNOFF)
print(f"Total P: {total_precip:.0f} mm")
print(f"Total ET: estimated from LH sum")
print(f"Delta S: {delta_s.mean():.0f} mm")
```

**Known issue**: Water balance does NOT close perfectly when routing is enabled, because SFCRNOFF includes routed flow (dt_v009). For cell-level water balance, disable routing (OVRTSWCRT=0, SUBRTSWCRT=0) and use headwater cells only. For basin-level balance, use CHRTOUT discharge at the outlet.

### Step 6: Namelist Settings That Control Output

#### In namelist.hrldas:

| Setting | Controls | Recommended | Warning |
|---------|----------|-------------|---------|
| `RESTART_FREQUENCY_HOURS` | LDASOUT + GWOUT write frequency | -9999 (every output step) or 24 (daily) | **0 = NO output** (dt_015) |
| `OUTPUT_TIMESTEP` | Output interval (seconds) | 86400 (daily) or 3600 (hourly) | Hourly = 24x more files |

#### In hydro.namelist:

| Setting | Controls | Recommended | Warning |
|---------|----------|-------------|---------|
| `CHRTOUT_DOMAIN` | Enable CHRTOUT files | **1** (MUST be 1) | **0 = no discharge output** |
| `CHRTOUT_GRID` | Grid-format channel output | **0** | 1 crashes with large LCC coords (dt_004) |
| `RTOUT_DOMAIN` | Enable RTOUT files | 0 (unless flood mapping needed) | Large files at high resolution |
| `output_gw` | Enable GWOUT files | 1 | 0 = no GW diagnostics |
| `output_channelBucket_influx` | GW recharge diagnostics | 0 | Enable for GW debugging |
| `out_dt` | Routing output interval (minutes) | 1440 (daily) | Must match OUTPUT_TIMESTEP / 60 |

### Step 7: Comparison with CaMa-Flood Output

For basins where both WRF-Hydro routing and CaMa-Flood are available:

| What you want | WRF-Hydro source | CaMa-Flood source |
|--------------|-------------------|-------------------|
| Channel discharge | CHRTOUT `streamflow` (m3/s) | `outflw` (m3/s) |
| River depth | RTOUT `sfcheadsubrt` at channel cells (m) | `rivdph` (m) |
| Flood depth | RTOUT `sfcheadsubrt` (m) -- no floodplain model | `flddph` (m) -- with floodplain exchange |
| Flood fraction | Not available | `fldfrc` (0-1) -- subgrid floodplain |
| Water surface elevation | Not available | `sfcelv` (m) |

**Key difference**: WRF-Hydro provides flood output on the routing grid but has no floodplain model. CaMa-Flood has explicit river-floodplain exchange with subgrid topography. CaMa-Flood is much more suitable for flood inundation mapping and depth estimation.

## Expected Outputs

After successful interpretation, the following should be available:

| Output | Path | Verification |
|--------|------|--------------|
| Outlet discharge timeseries | Extracted from CHRTOUT | Non-zero values during rain events |
| Basin-mean soil moisture | Masked from LDASOUT | Between SMCWLT and SMCMAX |
| ET components | From LDASOUT ETRAN+EDIR+ECAN | Positive, seasonal cycle present |
| GW bucket depth | From GWOUT z_gwsubbas | Between 0 and Zmax |
| Water balance | Computed from all sources | Closure error < 5% of P |

## Validation Checks

Run these checks after extracting output:

1. **CHRTOUT has non-zero discharge**: At the outlet feature
   - Command: `python -c "import netCDF4 as nc; ds=nc.Dataset('<latest_CHRTOUT>'); q=ds['streamflow'][:]; print(f'Max Q: {q.max():.1f} m3/s, Mean Q: {q.mean():.2f} m3/s')"`
   - Expected: Max Q > 0 during rain events; Mean Q > 0 for post-spinup period
   - If zero: AGGFACTRT mismatch (dt_014), no surface runoff (dt_v018), or no channels (dt_v016)

2. **SFCRNOFF is NOT used for discharge**: Verify extraction method
   - Expected: Discharge comes from CHRTOUT, not LDASOUT
   - If basin-average SFCRNOFF was used: Results are 2.4x overestimated (dt_v009)

3. **Spinup discarded**: First 6 months removed
   - Command: Check that analysis start date is >= simulation start + 6 months
   - Expected: No 237 mm/day spikes in the analysis period
   - If present: Spinup not removed (dt_v014)

4. **Output file count matches period**: Verify no gaps
   - Command: `ls *.CHRTOUT_DOMAIN1 | wc -l` vs expected count (days in period)
   - Expected: Count = (end_date - start_date + 1) for daily output
   - If fewer: Forcing files may have been insufficient (dt_005)

5. **Seasonal cycle direction**: For monsoon basins
   - Expected: Summer Q > Winter Q
   - If inverted: GW bucket dominance (dt_v017) -- fix channels and REFKDT first

## Common Pitfalls

> **PITFALL**: Using SFCRNOFF basin average for discharge
> Basin-averaged SFCRNOFF from LDASOUT gives 2.4x overestimate because it includes routed upstream flow at channel cells. Headwater cells show correct Q/P=0.35, but channel cells show Q/P=0.96.
> **Do this instead**: Extract discharge from CHRTOUT `streamflow` at the outlet feature_id. This is the only correct source for basin discharge.
> See diagnostic triplet dt_v009 for full details.

> **PITFALL**: No LDASOUT files produced (RESTART_FREQUENCY_HOURS = 0)
> RESTART_FREQUENCY_HOURS = 0 silently suppresses ALL LDASOUT and GWOUT output. Model runs successfully, shows "The model finished successfully" in stdout, but the output directory has only CHRTOUT files or nothing.
> **Do this instead**: Set RESTART_FREQUENCY_HOURS = -9999 (every timestep) or 24 (daily) in namelist.hrldas. Always verify output files exist after the first few timesteps.
> See diagnostic triplet dt_015 for full details.

> **PITFALL**: CHRTOUT_GRID = 1 crashes with large LCC coordinates
> If the projection origin is far from the basin, LCC x/y coordinates exceed 1e6 m. CHRTOUT_GRID=1 tries to write these as single-precision float attributes and fails with "Unable to place x floating point attributes".
> **Do this instead**: Set CHRTOUT_GRID = 0 in hydro.namelist. Use CHRTOUT_DOMAIN = 1 instead (1D output, no coordinate issue).
> See diagnostic triplet dt_004 for full details.

> **PITFALL**: Evaluating model performance using first-month output
> Cold-start spinup produces 237 mm/day runoff on day 1 and unrealistic soil moisture for the first 6-12 months. Any evaluation metric (NSE, RMSE, correlation) computed on this period will be meaninglessly bad.
> **Do this instead**: Always discard the first 6-12 months as spinup. Or use a RESTART file from a prior spinup run to skip the spinup artifact entirely.
> See diagnostic triplet dt_v014 for full details.

> **PITFALL**: Confusing UGDRNOFF (recharge TO bucket) with baseflow (FROM bucket)
> LDASOUT UGDRNOFF is the drainage FROM soil TO the GW bucket (recharge input). It is NOT the baseflow that enters the channel network. Actual baseflow is qout_gwsubbas in GWOUT files.
> **Do this instead**: For baseflow analysis, read GWOUT qout_gwsubbas. For soil drainage and recharge analysis, read LDASOUT UGDRNOFF. These are related but different quantities with different timing.

> **PITFALL**: Water balance does not close when routing is enabled
> With OVRTSWCRT=1 and SUBRTSWCRT=1, SFCRNOFF includes routed upstream flow, making per-cell water balance impossible. The same water is counted multiple times at different cells.
> **Do this instead**: For cell-level water balance, use only headwater cells (no upstream contributors) or disable routing temporarily. For basin-level balance, use CHRTOUT outlet discharge as the Q term.
> See diagnostic triplet dt_v009 for full details.

---

*This skill document is part of the `hydrocraft-wrfhydro-standalone` knowledge infrastructure.*
*Stage s11 of 12 | Tools used: (manual analysis) | Related triplets: dt_004, dt_015, dt_v009, dt_v014, dt_v017*
