# S2-S3: Soil Parameters and Land Cover Skill

## Purpose

Derive the HEC-HMS loss-method parameters used by this KI from HWSD soil texture
and AVHRR land cover. The implemented stage is `tools/convert_soil_to_hms.py`,
which maps HWSD texture classes to hydrologic soil groups, combines those groups
with AVHRR land-cover classes, and writes basin-average SCS Curve Number and
Green-Ampt reference parameters.

## Inputs

| Input | Format | Required by |
|-------|--------|-------------|
| HWSD soil raster | GeoTIFF/IMG raster | `--soil_file` |
| AVHRR land-cover raster | GeoTIFF raster | `--landcover_file` |
| Basin shapefile | `.shp`, readable by geopandas | `--basin_shp` |

## Outputs

| Output | Format | Produced by |
|--------|--------|-------------|
| Soil parameter file | JSON | `--output_file` |
| `curve_number` | dimensionless | `tools/convert_soil_to_hms.py` |
| `soil_groups` | A/B/C/D fractions | `tools/convert_soil_to_hms.py` |
| `green_ampt` | suction, Ksat, porosity, deficit | `tools/convert_soil_to_hms.py` |

## Procedure

1. Run the KI preflight first so missing raster/geospatial dependencies are caught
   before parameter generation:

   ```bash
   cd KISSPATH_KI_ROOT/HEC_HMS/knowledge_infrastructure
   python3 preflight_check.py
   ```

2. Convert HWSD and AVHRR into the JSON consumed by `tools/run_hec_hms.py`:

   ```bash
   python3 tools/convert_soil_to_hms.py \
     --soil_file KISSPATH_STATIC/HWSD_China_Geo.img \
     --landcover_file KISSPATH_DATA/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif \
     --basin_shp KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
     --output_file ./params/soil_params.json
   ```

3. Preserve the JSON as the stage handoff to model execution. `tools/run_hec_hms.py`
   reads its `curve_number` field when passed through `--soil_params`.

## Verification

- Confirm the command exits successfully and prints a basin-average CN.
- Inspect `./params/soil_params.json` and verify `curve_number` is in the
  valid SCS-CN range used by `run_hec_hms.py`.
- Confirm `soil_groups` contains A/B/C/D fractions that sum to approximately 1.0.
- Confirm `green_ampt.ksat_cm_hr` is positive and `green_ampt.porosity` is between
  0 and 1.

## Traps

- **dt_103**: A failed HWSD overlap or bad soil lookup can produce CN below 30,
  NaN, or zero. The remedy is to verify basin/raster overlap and CRS before using
  the generated JSON.
- **dt_111**: Green-Ampt suction or conductivity outside the lookup-table ranges
  indicates the soil class mapping or raster values are wrong.
- **dt_104**: The generated JSON reports initial abstraction notes, but the actual
  Ia ratio is selected during execution or calibration; using 0.20 in humid basins
  can understate runoff volume.

## Example

```bash
cd KISSPATH_KI_ROOT/HEC_HMS/knowledge_infrastructure
mkdir -p params
python3 tools/convert_soil_to_hms.py \
  --soil_file KISSPATH_STATIC/HWSD_China_Geo.img \
  --landcover_file KISSPATH_DATA/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif \
  --basin_shp KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
  --output_file ./params/soil_params.json
```
