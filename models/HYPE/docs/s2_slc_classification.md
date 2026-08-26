# s2_slc_classification

## Purpose

Compute HYPE SLC fractions and write `GeoClass.txt` definitions. HYPE routes water through subbasin fractions of soil-land use classes, so this stage establishes the land-use, soil, water, crop, vegetation, and soil-layer structure used by `GeoData.txt` and `par.txt`.

## Inputs

- Subbasin shapefile from s1: `--subbasins`
- AVHRR land cover directory or raster: `--landcover`
- HWSD soil raster: `--soil_raster`
- Optional default SLC mode: `--default_slc`
- SLC definitions CSV produced by `compute_slc_fractions.py`

## Outputs

- `slc_fractions.csv`
- `slc_definitions.csv`
- `GeoClass.txt` in the run `modelfiles/` directory

## Procedure

Compute SLC fractions:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s2_slc_classification/compute_slc_fractions.py \
  --subbasins outputs/hype_run/subbasins/subbasins.shp \
  --landcover data/vegetation/AVHRR/ \
  --soil_raster data/soil/HWSD_RASTER/hwsd.bil \
  --output outputs/hype_run/slc/
```

Generate `GeoClass.txt`:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s2_slc_classification/generate_geoclass.py \
  --slc_defs outputs/hype_run/slc/slc_definitions.csv \
  --output outputs/hype_run/modelfiles/GeoClass.txt
```

Only add `--enable_lakes` when `LakeData.txt` will be generated in s6.

## Verification

- `GeoClass.txt` has no text header row except `!!` comments.
- Each SLC row has `numlayers` between 1 and 3 and exactly that many soil-depth columns.
- Non-water land classes have `streamdepth > 0`.
- Water classes use `special=2` only when lake data is intentionally configured.

## Traps

- `dt_r03`: `GeoClass.txt` has invalid `numlayers` or mismatched soil-depth columns, causing HYPE soil-layer errors.
- `dt_s04`: water or lake classes are not marked `special=2`, so lake regulation has no downstream effect.
- `dt_s08`: land classes have `streamdepth=0`, so HYPE can run with valid precipitation but produce zero discharge.

## Example

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s2_slc_classification/compute_slc_fractions.py \
  --subbasins outputs/hype_run/subbasins/subbasins.shp \
  --landcover data/vegetation/AVHRR/ \
  --soil_raster data/soil/HWSD_RASTER/hwsd.bil \
  --output outputs/hype_run/slc/

python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s2_slc_classification/generate_geoclass.py \
  --slc_defs outputs/hype_run/slc/slc_definitions.csv \
  --output outputs/hype_run/modelfiles/GeoClass.txt \
  --enable_lakes
```
