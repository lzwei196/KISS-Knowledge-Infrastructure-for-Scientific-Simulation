# Domain Setup (GRU/HRU Definition) -- Skill Document

> **Stage ID**: s1_domain_setup
> **Pipeline order**: 1 of 7
> **Depends on**: none

## Purpose

Define the spatial structure of the SUMMA simulation: Grouped Response Units (GRUs) and Hydrologic Response Units (HRUs). Each GRU is a contiguous spatial unit (typically a grid cell). Each HRU within a GRU has uniform land cover and soil type. This determines how SUMMA distributes computations across space. If skipped, SUMMA has no spatial domain to simulate.

## Prerequisites

Before starting this stage, verify:

- [ ] Basin boundary shapefile exists (from HydroCraft delineation or external source)
- [ ] DEM raster covers the basin extent (GeoTIFF format)
- [ ] Land cover raster available (MODIS IGBP or USGS classification)
- [ ] Soil type raster available (from HWSD or regional soil map)
- [ ] All rasters and shapefile in the same CRS (recommend EPSG:4326 / WGS84)
- [ ] Python environment activated with geopandas, rasterio, netCDF4

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| basin_shp | file | HydroCraft delineation or user | Basin boundary shapefile (.shp) |
| dem_file | file | data/dem/ | Digital Elevation Model raster |
| landcover_file | file | data/landcover/ or MODIS | Land cover classification raster |
| soiltype_file | file | data/soil/HWSD_RASTER/ | Soil type raster |
| resolution | value | user choice | Grid resolution in degrees (0.25 or 0.1) |

## Procedure

Follow these steps in exact order.

### Step 1: Verify CRS consistency

Before any spatial operation, confirm all inputs share the same CRS.

```bash
python -c "
import geopandas as gpd, rasterio
shp = gpd.read_file('<basin_shp>')
dem = rasterio.open('<dem_file>')
print(f'Shapefile CRS: {shp.crs}')
print(f'DEM CRS: {dem.crs}')
assert str(shp.crs) == str(dem.crs), 'CRS MISMATCH -- reproject before proceeding'
"
```

**Expected result**: Both CRS values match (e.g., EPSG:4326).

**If this fails**: Reproject the shapefile to match the DEM: `gdf.to_crs(dem.crs).to_file(...)`. See diagnostic triplet dt_018.

### Step 2: Create GRU/HRU structure

```bash
python tools/s1_domain_setup/create_gru_hru.py \
  --basin_shp <basin_shp> \
  --dem <dem_file> \
  --landcover <landcover_file> \
  --soiltype <soiltype_file> \
  --resolution <0.25 or 0.1> \
  --output_dir outputs/<run_name>/summa_domain/
```

**Expected result**: `gru_hru_mapping.csv` created with columns gruId, hruId, lat, lon, elevation, area_m2, tan_slope, vegTypeIndex, soilTypeIndex.

**If this fails**: Check that rasters cover the basin extent. See diagnostic triplet dt_018.

### Step 3: Create local attributes NetCDF

```bash
python tools/s1_domain_setup/create_local_attributes.py \
  --gru_hru_csv outputs/<run_name>/summa_domain/gru_hru_mapping.csv \
  --output_nc outputs/<run_name>/summa_settings/attributes.nc
```

**Expected result**: `attributes.nc` created with hru and gru dimensions.

**If this fails**: Check that CSV has all required columns.

### Step 4: Validate attributes

```bash
ncdump -h outputs/<run_name>/summa_settings/attributes.nc
```

**Expected result**: Dimensions hru and gru present; variables gruId, hruId, latitude, longitude, elevation, HRUarea, tan_slope, vegTypeIndex, soilTypeIndex all present.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| GRU/HRU mapping | `outputs/<run>/summa_domain/gru_hru_mapping.csv` | Row count > 0, all columns present |
| Attributes NetCDF | `outputs/<run>/summa_settings/attributes.nc` | Has hru dimension, all required variables |

## Validation Checks

1. **HRU count is reasonable**: For a basin of area A km2 at resolution R degrees, expect roughly A / (R * 111)^2 GRUs, each with 1-5 HRUs.
   - Command: `ncdump -h attributes.nc | grep 'hru ='`
   - Expected: Number matches basin area and resolution
   - If unexpected: Check shapefile/DEM overlap. See dt_018.

2. **Elevation values are realistic**: Mean elevation should match known basin characteristics.
   - Command: `ncdump -v elevation attributes.nc | tail -5`
   - Expected: Values in plausible range for the region
   - If unexpected: DEM may not cover basin. See dt_018.

3. **No duplicate HRU IDs**: Each hruId must be unique.
   - Command: `ncdump -v hruId attributes.nc | python -c "import sys; ids=[int(x) for x in sys.stdin.read().split() if x.isdigit()]; print(f'Unique: {len(set(ids))}, Total: {len(ids)}')" `
   - Expected: Unique == Total

## Common Pitfalls

> **PITFALL**: CRS mismatch between shapefile and DEM.
> This happens when the shapefile uses UTM and the DEM uses WGS84. The symptom is all HRUs having identical default values. **Do this instead**: Always reproject to EPSG:4326 before running. See diagnostic triplet dt_018.

> **PITFALL**: Land cover raster has different classification system than expected.
> SUMMA's VEGPARM.TBL assumes MODIFIED_IGBP_MODIS_NOAH (20 classes) or USGS (27 classes). If your raster uses a different scheme, vegTypeIndex will map to wrong parameters. **Do this instead**: Verify classification scheme matches vegeParTbl decision.

---

*This skill document is part of the hydrocraft-summa knowledge infrastructure.*
*Stage 1 of 7 | Tools used: create_gru_hru, create_local_attributes | Related triplets: dt_010, dt_018*
