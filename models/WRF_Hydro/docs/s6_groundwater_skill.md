# Groundwater Bucket Model -- Skill Document

> **Stage ID**: s6_groundwater
> **Pipeline order**: 6 of 12 (part of groundwater/ancillary file construction)
> **Depends on**: s1_domain, s2_geo_em

## Purpose

WRF-Hydro's groundwater (GW) bucket model provides a simple conceptual representation of subsurface water storage and baseflow generation. It receives recharge from Noah-MP's subsurface drainage and releases baseflow back into the channel network using an exponential storage-discharge relationship. When properly calibrated, the GW bucket controls the recession limb and dry-season flow. When misconfigured, it can dominate the entire hydrograph, producing an inverted seasonal cycle in monsoon basins (dt_v017). This document covers the bucket model physics, parameter effects, GWBASINS setup, and calibration strategy based on verified results from Chaohe and Bengbu testing.

## Prerequisites

Before configuring the groundwater bucket, verify:

- [ ] `geo_em.d01.nc` exists with LANDMASK (determines which cells are land)
- [ ] `domain_def.json` exists with grid projection and dimensions
- [ ] Basin shapefile is available for basin mask rasterization
- [ ] Decision made on single-basin vs multi-basin configuration
- [ ] `build_groundwater.py` tool is available

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| `geo_em.d01.nc` | file | s2_geo_em | Geogrid file with LANDMASK, ISLTYP, IVGTYP |
| `domain_def.json` | file | s1_domain | Grid projection and dimensions |
| Basin shapefile | file | User/delineation | Basin boundary for rasterization |
| `HYDRO.TBL` | lookup table | WRF-Hydro distribution | Soil/veg parameters for hydro2dtbl.nc |
| `Coeff` | float | GWBUCKPARM.nc | Baseflow coefficient |
| `Expon` | float | GWBUCKPARM.nc | Baseflow nonlinearity exponent |
| `Zmax` | float (mm) | GWBUCKPARM.nc | Maximum bucket depth |
| `Zinit` | float (mm) | GWBUCKPARM.nc | Initial bucket water depth |

## Procedure

Follow these steps in exact order. Do not skip, reorder, or improvise.

### Step 1: Understand the Bucket Model Physics

**How the GW bucket works**:

The bucket model represents the entire basin (or sub-basin) aquifer as a single lumped reservoir. Water enters from Noah-MP subsurface drainage (percolation from the bottom soil layer) and exits as baseflow into the channel network.

**Storage-discharge relationship**:

```
Q_gw = Coeff * (exp(Expon * z / Zmax) - 1)
```

Where:
- `Q_gw` = groundwater discharge (baseflow) to channels (m3/s)
- `Coeff` = baseflow coefficient (controls magnitude)
- `Expon` = nonlinearity exponent (controls shape of release curve)
- `z` = current water depth in bucket (mm)
- `Zmax` = maximum bucket depth (mm)

**Physical interpretation**:
- When `z = 0`: Q_gw = Coeff * (exp(0) - 1) = 0 (empty bucket, no baseflow)
- When `z = Zmax`: Q_gw = Coeff * (exp(Expon) - 1) (full bucket, maximum baseflow)
- Higher `Expon`: more nonlinear -- baseflow increases rapidly as bucket fills
- Higher `Coeff`: more baseflow at any given water level

**Water balance**:
```
dz/dt = Recharge_in - Q_gw_out
```
Where `Recharge_in` comes from Noah-MP's bottom-layer drainage (UGDRNOFF).

### Step 2: Understand Parameter Effects

| Parameter | Default | Effect | Physical Analogy |
|-----------|---------|--------|-----------------|
| **Coeff** | 1.0 | Scales baseflow magnitude at all storage levels. Higher = more baseflow per unit storage. | Aquifer transmissivity -- how easily water flows through the subsurface |
| **Expon** | 3.0 | Controls nonlinearity. Higher = baseflow increases more steeply as bucket fills; lower = more linear (constant drainage rate). | Aquifer geometry -- confined (linear, low Expon) vs unconfined with variable transmissivity (nonlinear, high Expon) |
| **Zmax** | 50 mm | Maximum storage capacity. Higher = more water stored before overflow; longer memory; slower response to forcing changes. | Aquifer depth and porosity -- deeper aquifer = larger Zmax |
| **Zinit** | 10 mm | Initial water depth (cold start only). Controls initial baseflow before spinup equilibrates. | Antecedent moisture condition -- set to ~20% of Zmax for typical conditions |

### Step 3: Recognize When the Bucket Dominates (dt_v017)

**Symptom**: Discharge is inversely correlated with precipitation -- highest in winter, lowest in summer. This is physically wrong for monsoon basins.

**Root cause**: When the channel network has too few cells (dt_v016) or Noah-MP produces too little surface runoff (dt_v018), the only water reaching the outlet comes through the GW bucket. The bucket introduces phase lag and dampening:

1. Summer: High precipitation, but high ET depletes soil moisture, reducing recharge to the bucket. Meanwhile, bucket releases stored water from spring.
2. Winter: Low precipitation, but low ET means more water percolates to the bucket. Bucket accumulates water.
3. Result: Peak bucket discharge in late autumn/winter, minimum in spring/early summer -- inverted monsoon cycle.

**Diagnosis**: Plot monthly mean Q_gw (from GWOUT) vs monthly mean SFCRNOFF (from LDASOUT). If Q_gw >> SFCRNOFF at the outlet, the bucket dominates.

**Fix**: Address the upstream cause first:
1. Fix channel network (correct threshold, proper D8 encoding)
2. Reduce REFKDT to increase surface runoff
3. THEN tune GW parameters for the baseflow component

### Step 4: Run build_groundwater.py

```bash
python tools/s6_groundwater/build_groundwater.py \
  --geo_em DOMAIN/geo_em.d01.nc \
  --domain_json domain_def.json \
  --basin_shp data/shp/basin/basin.shp \
  --output_dir DOMAIN/
```

This creates four files:
1. **GWBASINS.nc** -- basin ID per LSM cell (single basin: all land cells = 1)
2. **GWBUCKPARM.nc** -- bucket parameters per basin ID
3. **hydro2dtbl.nc** -- 2D routing parameters (OV_ROUGH, LKSAT, SMCMAX1, etc.)
4. **GEOGRID_LDASOUT_Spatial_Metadata.nc** -- spatial reference for output files

**Expected result**: Four .nc files in DOMAIN/ directory. Console output shows basin cell count.

**If this fails**: Ensure basin shapefile CRS can be reprojected to the LCC projection in domain_def.json.

### Step 5: Verify GWBASINS Configuration

```python
import netCDF4 as nc
import numpy as np

ds = nc.Dataset("DOMAIN/GWBASINS.nc")
basin = ds["BASIN"][:]
ds.close()

unique_ids = np.unique(basin[basin > 0])
print(f"Basin IDs: {unique_ids}")
print(f"Total basin cells: {(basin > 0).sum()}")
```

**Critical rule**: Basin ID must be >= 1. Cells with Basin=0 are outside the GW domain. WRF-Hydro ignores recharge for cells not assigned to any basin.

**Single-basin setup** (default): All land cells within the basin shapefile get Basin=1. One set of parameters in GWBUCKPARM.nc. Sufficient for most applications.

**Multi-basin setup**: Split basin into sub-basins (e.g., by major tributary), assign different Basin IDs (1, 2, 3...), and provide separate parameters for each in GWBUCKPARM.nc. Useful when different parts of the basin have different hydrogeology.

To set up multi-basin:
```python
import geopandas as gpd
import netCDF4 as nc

# Load sub-basin shapefile with ID column
sub_basins = gpd.read_file("sub_basins.shp")
# Each polygon has a unique integer ID in column 'SUB_ID'
# Rasterize each polygon to the LSM grid with its ID
# Write to GWBASINS.nc BASIN variable
# Add one row per sub-basin in GWBUCKPARM.nc
```

### Step 6: Adjust Bucket Parameters

Edit GWBUCKPARM.nc directly:

```python
import netCDF4 as nc

ds = nc.Dataset("DOMAIN/GWBUCKPARM.nc", "a")
print(f"Current: Coeff={ds['Coeff'][0]:.2f}, Expon={ds['Expon'][0]:.2f}, "
      f"Zmax={ds['Zmax'][0]:.0f}, Zinit={ds['Zinit'][0]:.0f}")

# Adjust parameters:
ds["Coeff"][0] = 0.04    # Tier 1 calibration parameter
ds["Expon"][0] = 3.0     # Tier 2 calibration parameter
ds["Zmax"][0] = 200.0    # Increase from default 50 for deep aquifer basins
ds["Zinit"][0] = 40.0    # ~20% of Zmax

ds.close()
```

**Recommended ranges** (from calibration_guide.md and Chaohe/Bengbu testing):

| Parameter | Range | Default | Mountain | Flat alluvial | Deep aquifer |
|-----------|-------|---------|----------|---------------|-------------|
| Coeff | 0.001-0.5 | 1.0 | 0.01-0.05 | 0.03-0.10 | 0.001-0.01 |
| Expon | 1.0-8.0 | 3.0 | 2.0-4.0 | 1.5-3.0 | 3.0-6.0 |
| Zmax | 10-500 mm | 50 | 50-150 | 100-300 | 200-500 |
| Zinit | 0-Zmax | 10 | 10-30 | 20-60 | 40-100 |

### Step 7: Enable/Disable GW Bucket in Namelist

In `hydro.namelist`:

```fortran
! Baseflow bucket model: 1=exponential bucket, 0=off
GWBASESWCRT = 1

! GW cold start (0=cold start from Zinit, 1=restart from file)
GW_RESTART = 0

! GW basin mask file
gwbasmskfil = "./DOMAIN/GWBASINS.nc"

! GW bucket parameters file
GWBUCKPARM_file = "./DOMAIN/GWBUCKPARM.nc"
```

Set `GWBASESWCRT = 0` to disable the GW bucket entirely (all baseflow comes from Noah-MP's internal subsurface drainage only). This simplifies the model but eliminates recession dynamics.

### Step 8: Interpret GW Output (GWOUT Files)

GW output files (`*.GWOUT_DOMAIN1`) contain:

| Variable | Unit | Description |
|----------|------|-------------|
| `qin_gwsubbas` | m3/s | Recharge into bucket (from Noah-MP UGDRNOFF) |
| `qout_gwsubbas` | m3/s | Discharge from bucket (baseflow to channels) |
| `z_gwsubbas` | mm | Current water depth in bucket (z) |
| `qloss_gwsubbas` | m3/s | Deep percolation loss beyond bucket bottom |

**Diagnostic check**: After a test run, plot z_gwsubbas over time:
- If depth quickly reaches Zmax and stays there: Zmax too shallow (dt_v013). Increase to 200-500 mm.
- If depth stays near zero: Coeff too high (draining too fast) or no recharge (subsurface drainage disabled or REFKDT too high).
- If depth oscillates seasonally around a stable mean: Bucket is in equilibrium -- healthy behavior.

### Step 9: Calibrate Against Baseflow Recession

The GW bucket parameters should be calibrated Tier 3 (after REFKDT and channel parameters):

**Method -- recession analysis**:
1. Identify dry periods in observed discharge (no rain for >= 7 days)
2. Plot log(Q_obs) vs time during these periods
3. The slope of log(Q) gives the recession constant
4. Match this slope by adjusting Coeff and Expon:
   - Steep recession (fast draining): increase Zmax or decrease Coeff
   - Shallow recession (slow draining): decrease Zmax or increase Coeff
   - Curved recession (nonlinear): adjust Expon

**Sensitivity analysis from Chaohe testing**:
- Coeff 0.01 to 0.5: linear effect on baseflow magnitude
- Expon 1.5 to 6.0: controls whether baseflow is steady (low Expon) or "bursty" (high Expon)
- Zmax 50 to 500: controls recession timescale (50mm = days, 500mm = months)

## Expected Outputs

After successful completion, the following should exist:

| Output | Path | Verification |
|--------|------|--------------|
| GWBASINS.nc | `DOMAIN/GWBASINS.nc` | Contains BASIN variable, all land cells have ID >= 1 |
| GWBUCKPARM.nc | `DOMAIN/GWBUCKPARM.nc` | Contains Coeff, Expon, Zmax, Zinit per basin |
| hydro2dtbl.nc | `DOMAIN/hydro2dtbl.nc` | Contains LKSAT, OV_ROUGH2D, SMCMAX1, SMCREF1, SMCWLT1 |
| Spatial metadata | `DOMAIN/GEOGRID_LDASOUT_Spatial_Metadata.nc` | x/y coordinate variables with `resolution` attribute |
| GWOUT files (after run) | `<run_dir>/*.GWOUT_DOMAIN1` | qin_gwsubbas, qout_gwsubbas, z_gwsubbas variables present |

## Validation Checks

Run these checks before proceeding to the next stage:

1. **Basin ID minimum**: Verify all land cells have Basin >= 1
   - Command: `python -c "import netCDF4 as nc; ds=nc.Dataset('DOMAIN/GWBASINS.nc'); b=ds['BASIN'][:]; print('Min basin ID (land):', b[b>0].min() if (b>0).any() else 'NONE')"`
   - Expected: 1 (minimum valid Basin ID)
   - If 0 on land cells: Rasterization failed. Check shapefile CRS matches LCC projection.

2. **Parameter reasonableness**: Verify default parameters
   - Command: `python -c "import netCDF4 as nc; ds=nc.Dataset('DOMAIN/GWBUCKPARM.nc'); print(f'Coeff={ds[\"Coeff\"][0]:.3f}, Expon={ds[\"Expon\"][0]:.1f}, Zmax={ds[\"Zmax\"][0]:.0f}, Zinit={ds[\"Zinit\"][0]:.0f}')"`
   - Expected: Coeff=0.001-0.5, Expon=1-8, Zmax=50-500, Zinit<=Zmax
   - If Zmax=50 and basin has deep alluvial soils: Increase to 200-500 (dt_v013)

3. **Spatial metadata resolution attribute**: Verify the critical `resolution` attribute exists
   - Command: `python -c "import netCDF4 as nc; ds=nc.Dataset('DOMAIN/GEOGRID_LDASOUT_Spatial_Metadata.nc'); print('x resolution:', ds['x'].resolution)"`
   - Expected: Float value equal to LSM grid spacing (e.g., 1000.0 for 1km)
   - If AttributeError: Missing resolution attribute (dt_002). Add manually.

4. **GW bucket depth after test run**: Verify bucket is not perpetually full
   - Command: `python -c "import netCDF4 as nc; ds=nc.Dataset('<latest_GWOUT>'); print('Depth:', ds['z_gwsubbas'][:].mean(), 'mm')"`
   - Expected: Between 0 and Zmax (not pinned at Zmax)
   - If at Zmax: Bucket too shallow -- pure pass-through (dt_v013)

5. **Baseflow fraction**: Verify GW baseflow is reasonable fraction of total Q
   - Command: Compare GWOUT qout_gwsubbas sum to CHRTOUT streamflow sum
   - Expected: Baseflow fraction 20-60% for humid basins, 10-30% for arid basins
   - If > 80%: Channels too sparse (dt_v016) or REFKDT too high (dt_v018)

## Common Pitfalls

> **PITFALL**: Zmax=50mm (default) causes bucket to fill instantly
> This happens when the default Zmax=50mm is used for large alluvial basins with deep aquifers. The symptom is that the GW bucket fills within the first few days of simulation, all recharge passes through as immediate baseflow with zero delay, and the baseflow recession curve has no memory.
> **Do this instead**: Increase Zmax to 200-500mm for basins with deep soils and significant groundwater contributions. For mountain basins with thin soils, 50-150mm may be appropriate.
> See diagnostic triplet dt_v013 for full details.

> **PITFALL**: GW bucket produces inverted seasonal cycle (winter > summer discharge)
> This happens when the channel network is too sparse (zero or few channels) and Noah-MP produces near-zero surface runoff (REFKDT too high). The symptom is that all streamflow comes from the GW bucket, which has a lagged, dampened, and phase-shifted response relative to precipitation.
> **Do this instead**: Fix the upstream causes first: (1) Fix channel network with correct threshold and D8 encoding (dt_v016, dt_v007), (2) Reduce REFKDT from 3.0 to 0.5-1.0 to increase surface runoff (dt_v018). Only then tune GW parameters for the baseflow component.
> See diagnostic triplet dt_v017 for full details.

> **PITFALL**: Coeff=1.0 (default in build_groundwater.py) is too high for most basins
> This happens when using the tool's default Coeff=1.0 without calibration. The symptom is excessive baseflow magnitude, with Q_gw dominating the total discharge even when the channel network is functioning correctly.
> **Do this instead**: Start with Coeff=0.04 (calibration_guide.md recommended default) and calibrate against observed baseflow recession. Typical range is 0.001-0.5.

> **PITFALL**: Basin ID = 0 for land cells
> This happens when the basin shapefile does not fully cover the LSM grid or the CRS reprojection fails. The symptom is that some land cells have BASIN=0 in GWBASINS.nc, meaning their recharge is discarded (not routed to any GW bucket), effectively creating a water balance leak.
> **Do this instead**: Verify that `(basin_grid > 0).sum()` approximately equals the number of land cells in geo_em.d01.nc. If not, check that the shapefile fully covers the domain and the CRS matches the LCC projection.

> **PITFALL**: Interpreting GW bucket output as "real" groundwater
> This happens when users compare the bucket depth (z_gwsubbas) to observed water table measurements. The GW bucket is a **conceptual** model -- z is not the water table depth, Zmax is not the aquifer thickness, and Coeff is not the aquifer hydraulic conductivity. The bucket is a mathematical convenience for producing baseflow with the right recession characteristics.
> **Do this instead**: Calibrate bucket parameters against observed baseflow recession curves (from hydrograph separation), not against groundwater well measurements. The parameters are empirical, not physically-based.

> **PITFALL**: Tuning GW parameters without first fixing the channel network
> This happens when users observe poor discharge and start adjusting Coeff, Expon, Zmax. But if the channel network is broken (zero channels, wrong D8 encoding), GW bucket dominance is a symptom, not the disease. No combination of GW parameters can fix a missing channel network.
> **Do this instead**: Always verify channel network first (Step 3 in s4_channel_routing_skill.md). Only calibrate GW parameters as Tier 3, after REFKDT (Tier 1) and MannN/OVROUGHRTFAC (Tier 2).

---

*This skill document is part of the `hydrocraft-wrfhydro-standalone` knowledge infrastructure.*
*Stage s6 of 12 | Tools used: build_groundwater | Related triplets: dt_002, dt_v013, dt_v016, dt_v017*
