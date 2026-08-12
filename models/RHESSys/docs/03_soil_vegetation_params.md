# Stage 3: Soil and Vegetation Parameter Definition

## Purpose

Create parameter definition files (`.def`) for soil, vegetation, land use, and
other spatial objects. These files control the physical and biogeochemical
properties that drive RHESSys processes.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Soil properties | HWSD / SoilGrids / SSURGO | Sand%, clay%, depth, bulk density |
| Vegetation type | NLCD / GlobeLand30 / literature | Species, LAI, allometric parameters |
| Land use | NLCD / manual | Impervious fraction, fertilizer, irrigation |

## Outputs

| File | Location | Description |
|------|----------|-------------|
| `soil_*.def` | `defs/` | Soil hydraulic and biogeochemical parameters |
| `veg_*.def` | `defs/` | Vegetation ecophysiological parameters |
| `lu_*.def` | `defs/` | Land use parameters |
| `basin.def` | `defs/` | Basin-level defaults |
| `hill.def` | `defs/` | Hillslope-level defaults |
| `zone.def` | `defs/` | Zone-level defaults |

## Procedure

### Step 1: Soil Parameters

Key soil parameters and their units:

| Parameter | Unit | Typical Range | Description |
|-----------|------|---------------|-------------|
| `Ksat_0` | **m/day** | 0.001-100 | Surface saturated hydraulic conductivity |
| `m` | m | 0.01-20 | Transmissivity decay parameter |
| `porosity_0` | **m^3/m^3** | 0.2-0.7 | Surface porosity (fraction) |
| `porosity_decay` | 1/m | 0-10 | Porosity decay with depth |
| `pore_size_index` | dimensionless | 0.1-0.8 | Brooks-Corey parameter |
| `psi_air_entry` | **m** | 0.01-3.0 | Air entry pressure |
| `soil_depth` | **m** | 0.5-5.0 | Total soil depth |

**UNIT TRAPS:**
- `Ksat_0`: Must be m/day. HWSD reports cm/hr → multiply by 0.24 (dt_005)
- `porosity_0`: Must be fraction. Some databases report % → divide by 100 (dt_006)
- `soil_depth`: Must be m. Most databases report cm → divide by 100 (dt_004)
- `psi_air_entry`: Must be m (head). Some sources use kPa → divide by 9.81 (dt_010)

Pedotransfer functions (Cosby et al. 1984):
```
Ksat (inch/hr) = 10^(-0.6 + 0.0126*sand% - 0.0064*clay%)
porosity = 0.489 - 0.00126 * sand%
psi_ae (cm) = 10^(1.54 - 0.0095*sand% + 0.0063*silt%)
b = 3.10 + 0.157*clay% - 0.003*sand%
```

### Step 2: Vegetation Parameters

Key vegetation parameters:

| Parameter | Unit | Typical Range | Description |
|-----------|------|---------------|-------------|
| `epc.max_lai` | m^2/m^2 | 1-12 | Maximum leaf area index |
| `epc.proj_sla` | m^2/kg C | 0.01-1.0 | Specific leaf area |
| `epc.leaf_turnover` | 1/day | 0.0001-0.01 | Daily leaf turnover |
| `epc.livewood_turnover` | 1/day | 0.0001-0.01 | Livewood turnover |
| `epc.height_to_stem_coef` | m/(kgC/m^2) | 1-30 | Allometric coefficient |
| `epc.allocation_flag` | integer | 1-3 | C allocation strategy |
| `epc.veg_type` | integer | 1=tree, 2=grass | Vegetation type flag |

**TRAP:** Carbon/nitrogen pool values in the worldfile must be in **kg/m^2**,
not g/m^2 (dt_009). Initializing with g/m^2 values gives 1000x too much carbon.

### Step 2b: Carbon Pool Initialization (REQUIRED for -g runs)

**This step is always missing from bare worldfiles and causes LAI=0 / trans=0
throughout the entire simulation when running with the `-g` (carbon cycling) flag.**

The standard RHESSys workflow (RHESSysWorkflows by Nairb 2013) uses a `lairead`
utility to initialize carbon stores from an LAI raster. Our KI tool provides an
equivalent computation without requiring GRASS GIS.

**How it works (allometric equations from `util/GRASS/lairead/change_world.c`):**
```
leafc        = LAI / proj_sla
frootc       = leafc / alloc_frootc_leafc
leafn        = leafc / leaf_cn
frootn       = frootc / froot_cn
```

**Start-month semantics for DECIDUOUS (critical):**

| Start period | cs.leafc | cs.leafc_transfer | cs.leafc_store |
|---|---|---|---|
| Growing season (day_leafon..day_leafoff) | LAI/proj_sla | 0 | LAI/proj_sla |
| Dormant (Jan 1 for day_leafon=91) | 0 | max_lai/proj_sla | LAI/proj_sla |

**Why two pools matter:**
- `cs.leafc_transfer` is consumed during leaf expansion at day_leafon
- `cs.leafc_store` gets converted to `leafc_transfer` at annual allocation (end of growing season)
- Setting only `cs.leafc_store` for a dormant start leaves Year 1 with no leaves
  because annual allocation hasn't run yet (it runs at day_leafoff + ndays_litfall)

**Tool:**
```bash
python ki/tools/init_carbon_pools.py \
  --world worldfiles/basin_v1.world \
  --output worldfiles/basin_v1_init.world \
  --lai 3.5 \
  --proj-sla 20.0 \
  --max-lai 4.0 \
  --alloc-frootc-leafc 1.0 \
  --leaf-cn 35.0 \
  --froot-cn 60.0 \
  --veg-type GRASS \
  --phenology-type DECIDUOUS \
  --day-leafon 91 \
  --day-leafoff 270 \
  --start-month 1
```

Reference: https://github.com/selimnairb/RHESSysWorkflows

### Step 3: Land Use Parameters

```
1       landuse_default_ID
0.0     impervious_fraction        (0-1)
0.0     irrigation                 (m/day)
0.0     fertilizer_NO3             (kg N/m^2/year)
0.0     fertilizer_NH4             (kg N/m^2/year)
```

### Step 4: Basin/Hillslope/Zone Defaults

These are typically minimal:

**basin.def:**
```
1       basin_parm_ID
```

**zone.def:**
```
1       zone_parm_ID
0.0     atm_trans_lapse_rate
0.0     dewpoint_lapse_rate
-0.006  lapse_rate                 (C/m, temperature lapse rate)
```

## Verification

```bash
# Check soil parameter ranges
python3 -c "
for line in open('defs/soil_sandyloam.def'):
    parts = line.strip().split()
    if len(parts) >= 2 and parts[0][0].isdigit():
        val, name = float(parts[0]), parts[1]
        if name == 'Ksat_0' and val > 200:
            print(f'WARNING: Ksat_0={val} m/day too high (cm/hr not converted?)')
        if name == 'porosity_0' and val > 1:
            print(f'WARNING: porosity_0={val} > 1 (% not converted to fraction?)')
        if name == 'soil_depth' and val > 50:
            print(f'WARNING: soil_depth={val} m (cm not converted to m?)')
"
```

## Tool

```bash
python ki/tools/convert_soil_params.py \
  --sand 45 --clay 20 --depth 150 \
  --output-dir defs/ --prefix soil_loam

# Or from CSV:
python ki/tools/convert_soil_params.py \
  --input hwsd_extract.csv \
  --output-dir defs/ --prefix soil_site
```

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Ksat in cm/hr | Drainage 4x too fast | Multiply by 0.24 for m/day | dt_005 |
| Porosity as % | Porosity > 1 crashes model | Divide by 100 | dt_006 |
| Soil depth in cm | Model treats as m, 100x too deep | Divide by 100 | dt_004 |
| C/N pools in g/m^2 | 1000x excess biomass | Divide by 1000 | dt_009 |
| Psi air entry in kPa | Wrong suction curve | Convert to m of water | dt_010 |
| Zero carbon pools | LAI=0, trans=0 all run (silent) | Run init_carbon_pools.py | dt_011 |
| leafc_store only (dormant start) | LAI=0 Year 1 (leafc_transfer=0) | Also set cs.leafc_transfer | dt_012 |
| porosity_decay ≈ 4 | 100x slowdown, ~0.75 days/min | Use porosity_decay=3000 | dt_013 |
| Kdown_direct without Kdown_diffuse | Clear-sky radiation all days → vegetation collapse in 3-5 yr | Split total Kdown with Erbs model → provide both Kdown_direct (beam) + Kdown_diffuse | dt_014 |
| tmax−tmin constant (tavg±4°C) | MTCLIM cloud correction broken → same clear-sky fraction every day | Use measured tmax/tmin OR provide Kdown_direct+Kdown_diffuse (dt_014) | dt_015 |
| No daytime_rain_duration file | trans=0 on every rainy day (80-90% of days in monsoon climates) → annual trans 3-10x too low | Run gen_rain_duration.py to create `.daytime_rain_duration`; add to station file | dt_022 |
| rnet_evap bug (RHESSys 7.4) | trans=0 on cloudy days even when Kdown>0 (canopy_stratum_daily_F.c line 1160 typo) | Patch line 1160: `rnet_evap_night=0` → `rnet_evap_day=0`; recompile | dt_021 |

## Example

See `source/repo/Testing/defs/soil_sandyloam.def` and
`source/repo/Testing/defs/veg_douglasfir.def` for complete examples.
