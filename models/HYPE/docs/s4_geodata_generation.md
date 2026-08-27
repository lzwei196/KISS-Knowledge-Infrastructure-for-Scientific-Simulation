# s4_geodata_generation

## Purpose

Generate and validate `GeoData.txt`, the HYPE subbasin physiography table. This stage combines the s1 subbasins and MAINDOWN topology with s2 SLC fractions, optional DEM-derived elevation/slope, river length estimates, lake depth defaults, and subbasin areas.

## Inputs

- Subbasin shapefile from s1: `--subbasins`
- SLC fractions from s2: `--slc_fractions`
- MAINDOWN topology from s1: `--maindown`
- Optional DEM raster: `--dem`
- Optional default lake depth: `--lake_depth`

## Outputs

- `modelfiles/GeoData.txt`
- Validation report from `validate_geodata.py`

## Procedure

Generate `GeoData.txt`:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s4_geodata_generation/generate_geodata.py \
  --subbasins outputs/hype_run/subbasins/subbasins.shp \
  --slc_fractions outputs/hype_run/slc/slc_fractions.csv \
  --maindown outputs/hype_run/subbasins/maindown.csv \
  --dem data/dem/china_dem_90m/china_dem_90m.tif \
  --output outputs/hype_run/modelfiles/GeoData.txt
```

Validate before running HYPE:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s4_geodata_generation/validate_geodata.py \
  --geodata outputs/hype_run/modelfiles/GeoData.txt
```

## Verification

- `GeoData.txt` includes `SUBID`, `MAINDOWN`, `AREA`, `RIVLEN`, latitude/longitude, elevation/slope, and all `SLC_N` columns used by `GeoClass.txt`.
- Each row's SLC fractions sum to 1.0 within 0.001.
- `AREA` values are in m2, not km2.
- `RIVLEN` values are nonzero for routed land subbasins.
- Exactly one outlet has `MAINDOWN=0`, and `validate_geodata.py` exits successfully.

## Traps

- `dt_s01`: SLC fractions in `GeoData.txt` do not sum to 1.0, causing silent water-balance error.
- `dt_s02`: `AREA` is written in km2 instead of m2, scaling discharge by orders of magnitude.
- `dt_s06`: `RIVLEN=0` or too small removes routing delay and makes hydrographs unrealistically peaky.
- `dt_r05`: MAINDOWN contains a cycle instead of a downstream path to `MAINDOWN=0`.

## Example

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s4_geodata_generation/generate_geodata.py \
  --subbasins outputs/hype_run/subbasins/subbasins.shp \
  --slc_fractions outputs/hype_run/slc/slc_fractions.csv \
  --maindown outputs/hype_run/subbasins/maindown.csv \
  --dem data/dem/china_dem_90m/china_dem_90m.tif \
  --lake_depth 2.0 \
  --output outputs/hype_run/modelfiles/GeoData.txt

python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s4_geodata_generation/validate_geodata.py \
  --geodata outputs/hype_run/modelfiles/GeoData.txt
```
