# Stage 1: Surface Dataset Preparation

## Purpose

Create the surface dataset (surfdata_*.nc) that defines the land surface
properties for ELM: plant functional types, soil texture, topography, and
land use fractions. This is one of the most critical inputs — errors here
silently propagate through all simulated variables.

## Prerequisites

- Stage 0 completed (E3SM installed)
- Soil data source (HWSD, SoilGrids, or manual specification)
- Vegetation data source (MODIS land cover or PFT fractions)
- Target grid resolution defined

## Inputs

| Input | Format | Units | Description |
|-------|--------|-------|-------------|
| Sand fraction | % (0-100) | percent | Per soil layer, from HWSD or SoilGrids |
| Clay fraction | % (0-100) | percent | Per soil layer, from HWSD or SoilGrids |
| Soil organic matter | kg/m³ | density | Decreases with depth |
| PFT fractions | % (0-100) | percent | Must sum to 100% per grid cell |
| Monthly LAI | m²/m² | — | 12 monthly values per PFT |
| Elevation | m | meters | From DEM (SRTM, ASTER) |
| Land fraction | 0-1 | fraction | Land/ocean mask |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| surfdata_*.nc | NetCDF | Complete surface dataset for ELM |
| Validation log | JSON | Quality checks and warnings |

## Procedure

### Option A: Using ELM's mksurfdata_map tool (recommended for global runs)

```bash
cd components/elm/tools/mksurfdata_map/src
gmake
cd ..
./mksurfdata_map -r ne4pg2 -y 2000
```

### Option B: Using our KI tool (for point/regional studies)

```bash
# From HWSD data
python tools/convert_surface_data.py \
    --lat 40.0 --lon 117.0 \
    --from_hwsd /path/to/hwsd.csv \
    --output surfdata_point.nc

# Manual specification
python tools/convert_surface_data.py \
    --lat 40.0 --lon 117.0 \
    --sand 45.0 --clay 20.0 --organic 25.0 \
    --pft_type 7 --pft_frac 80.0 \
    --output surfdata_point.nc

# From USDA texture class
python tools/convert_surface_data.py \
    --lat 40.0 --lon 117.0 \
    --texture_class loam \
    --pft_type 13 --pft_frac 100.0 \
    --output surfdata_point.nc
```

### Step-by-step

1. **Identify soil properties** for your study region from HWSD, SoilGrids, or
   field measurements.

2. **Determine PFT composition**:
   - Use MODIS MCD12Q1 land cover to derive PFT fractions
   - Or specify dominant PFT manually (see PFT table below)

3. **Run the converter** with validate→process→validate pattern.

4. **Inspect the output** with `ncdump -h surfdata_point.nc` to verify
   all required variables are present.

## PFT Reference Table

| Index | Name | Typical Biome |
|-------|------|---------------|
| 0 | Bare ground | Desert, rock |
| 1 | Needleleaf evergreen temperate tree | Pacific NW forest |
| 2 | Needleleaf evergreen boreal tree | Boreal/taiga |
| 3 | Needleleaf deciduous boreal tree | Siberian larch |
| 4 | Broadleaf evergreen tropical tree | Tropical rainforest |
| 5 | Broadleaf evergreen temperate tree | Subtropical forest |
| 6 | Broadleaf deciduous tropical tree | Monsoon forest |
| 7 | Broadleaf deciduous temperate tree | Temperate deciduous |
| 8 | Broadleaf deciduous boreal tree | Boreal birch/aspen |
| 9 | Broadleaf evergreen shrub | Mediterranean chaparral |
| 10 | Broadleaf deciduous temperate shrub | Temperate shrubland |
| 11 | Broadleaf deciduous boreal shrub | Arctic/alpine shrub |
| 12 | C3 arctic grass | Tundra |
| 13 | C3 non-arctic grass | Temperate grassland |
| 14 | C4 grass | Tropical/subtropical grassland |

## Verification

- [ ] `ncdump -h surfdata.nc` shows all required variables
- [ ] PCT_SAND + PCT_CLAY ≤ 100% for all layers (dt_007)
- [ ] PCT_NAT_PFT sums to 100% per grid cell (dt_015)
- [ ] MONTHLY_LAI values in range 0-12 m²/m² (dt_006)
- [ ] ORGANIC values in range 0-130 kg/m³ (dt_011)
- [ ] Coordinates match the target grid

## Traps

| Trap | dt_ID | Symptom | Prevention |
|------|-------|---------|------------|
| sand + clay > 100% | dt_007 | Fatal crash, invalid hydraulic params | Always compute silt = 100 - sand - clay |
| PFT sum ≠ 100% | dt_015 | Missing land area, energy imbalance | Normalize fractions after assignment |
| LAI too high | dt_006 | Unrealistic GPP, canopy closure | Check range: 0-12 m²/m² |
| Organic in wrong units | dt_011 | Wrong soil thermal conductivity | Must be kg/m³, not % or g/g |
| Wrong grid orientation | dt_014 | Forcing applied to wrong location | Verify latitude increases S→N |

## Example

```bash
# Generate surface data for a temperate deciduous forest site
python tools/convert_surface_data.py \
    --lat 42.5 --lon -72.2 \
    --sand 55 --clay 15 --organic 30 \
    --pft_type 7 --pft_frac 85.0 \
    --output surfdata_harvard_forest.nc

# Verify
python -c "
import netCDF4 as nc
ds = nc.Dataset('surfdata_harvard_forest.nc')
print('Sand:', ds.variables['PCT_SAND'][0,0,0])
print('PFT sum:', ds.variables['PCT_NAT_PFT'][:,0,0].sum())
ds.close()
"
```
