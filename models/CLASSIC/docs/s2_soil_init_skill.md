# Stage 2: Soil and Initialization File Preparation

## Purpose

Build a CLASSIC initialization netCDF file containing soil texture, vegetation parameters, and initial values of all prognostic variables. This is the most complex input file, with ~50+ variables spanning soil, vegetation, carbon, and model state.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Soil texture (sand, clay, organic) | HWSD, GSDE, SoilGrids | % or fraction |
| Soil depth | Shangguan et al. (2017) or local data | m or cm |
| PFT fractions | LUH2, MODIS land cover | fraction |
| Soil colour index | Lawrence and Chase (2007) | index 1-20 |
| Initial temperature | ERA5 soil temp or climatology | deg C |
| Initial soil moisture | ERA5 or field capacity estimate | m3/m3 |

## Outputs

Single netCDF-4 file (`init_file.nc`) with dimensions:
- `tile` (1 for single tile), `lat` (1), `lon` (1)
- `layer` (typically 20 ground layers)
- `ic` (4 CLASS PFTs), `icc` (9 CTEM PFTs), `icp1` (5 = ic+1), `iccp1` (10), `iccp2` (11)

## Procedure

1. **Determine soil texture** for each layer
   - CLASSIC uses SAND, CLAY, ORGM as **percentages (0-100)**
   - Special SAND flags: -2 = peat, -3 = bedrock, -4 = ice sheet
   - Set layers below SDEP to SAND = -3 (bedrock)

2. **Configure soil layers** (DELZ)
   - Default: 20 layers, 0.10-0.50 m each, total ~6.1 m
   - Minimum layer thickness ~0.10 m (explicit scheme stability)

3. **Set vegetation parameters**
   - Map land cover to CLASSIC PFTs (NdlTr, BdlTr, Crops, Grass)
   - Set FCAN (CLASS fracs), fcancmx (CTEM fracs)
   - Assign albedo (ALVC, ALIC), LAI range (PAMN, PAMX), canopy mass (CMAS), roughness (LNZ0), rooting depth (ROOT)

4. **Initialize prognostic variables**
   - Soil temperature (TBAR): Use climatological mean or ERA5
   - Soil moisture (THLQ): Initialize to field capacity (~0.3 m3/m3)
   - Frozen moisture (THIC): Set to 0 if TBAR > 0
   - Snow: Initialize to zero (start in snow-free period)
   - Carbon pools: Small positive values or zero (will spin up)

5. **Write netCDF-4** with all required variables and proper dimensions

## Verification

```python
import netCDF4 as nc
ds = nc.Dataset("init_file.nc")
sand = ds.variables["SAND"][0, :, 0, 0]
assert all(s >= -4 for s in sand), "Invalid SAND values"
assert all(s <= 100 for s in sand), "SAND > 100, likely wrong units"
delz = ds.variables["DELZ"][:]
assert all(d >= 0.05 for d in delz), "Layers too thin, may cause instability"
tbar = ds.variables["TBAR"][0, 0, 0, 0]
assert -60 < tbar < 50, "Initial temperature out of range (should be deg C)"
ds.close()
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Soil texture as fraction (0-1) not % | Wrong soil hydraulic properties, model may crash | Multiply by 100 |
| SDEP in cm not m | Soil column 100x too deep | Divide by 100 |
| DELZ in cm not m | Layers 100x too thick, wrong thermal behavior | Divide by 100 |
| ROOT in cm not m | Roots extend 100x too deep | Divide by 100 |
| TBAR in K not C | Model computes wrong soil phase changes | Subtract 273.15 |
| Missing DELZ variable | Model crashes on initialization | Must be present in init file |
| Carbon pools in gC/m2 not kgC/m2 | Pools 1000x too large | Divide by 1000 |
| PFT fracs sum > 1 | Model violates area conservation | Normalize to sum <= 1 |
| nmtest missing or 0 | Model skips grid cell | Set to 1 |
| grclarea in m2 not km2 | Fire/LUC area calculations 1e6x wrong | Divide by 1e6 |

## Example

```bash
python ki/tools/convert_soil_to_classic.py \
    --lat 45.5 --lon -75.5 \
    --sand "70,65,60,60,55,55,50,50,45,45,45,45,45,45,45,45,45,45,45,45" \
    --clay "10,12,15,15,18,18,20,20,22,22,22,22,22,22,22,22,22,22,22,22" \
    --orgm "5,3,2,1,1,0.5,0.5,0.5,0,0,0,0,0,0,0,0,0,0,0,0" \
    --sdep 4.1 \
    --pft_fracs "0.3,0.1,0.0,0.1,0.0,0.1,0.0,0.2,0.1" \
    --output init_file.nc
```
