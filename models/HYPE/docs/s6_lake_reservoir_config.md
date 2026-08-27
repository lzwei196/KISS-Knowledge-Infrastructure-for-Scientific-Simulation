# s6_lake_reservoir_config

## Purpose

Configure optional HYPE outlet-lake and dam regulation files. This stage creates `LakeData.txt` and `DamData.txt` from `GeoData.txt`, `GeoClass.txt`, HydroLAKES, and GRanD-style lake/dam metadata, and can update `GeoData.txt` with `lakedataid` and lake depths.

## Inputs

- `modelfiles/GeoData.txt` from s4
- `modelfiles/GeoClass.txt` from s2
- Optional subbasin shapefile from s1
- Basin latitude/longitude and search radius
- Optional dam names or dam purpose filter

## Outputs

- `modelfiles/LakeData.txt`
- `modelfiles/DamData.txt`
- Optional updated `GeoData.txt` with lake metadata when `--update_geodata` is used

## Procedure

Generate lake data from HydroLAKES/GRanD lookup logic:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s6_lake_reservoir_config/generate_lakedata.py \
  --geodata outputs/hype_run/modelfiles/GeoData.txt \
  --geoclass outputs/hype_run/modelfiles/GeoClass.txt \
  --output outputs/hype_run/modelfiles/LakeData.txt \
  --lat 32.4 \
  --lon 115.7 \
  --search_radius_km 100 \
  --min_lake_area_km2 1.0 \
  --update_geodata
```

Generate dam regulation data:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s6_lake_reservoir_config/generate_damdata.py \
  --geodata outputs/hype_run/modelfiles/GeoData.txt \
  --output outputs/hype_run/modelfiles/DamData.txt \
  --lat 32.4 \
  --lon 115.7 \
  --search_radius_km 200
```

For a simple LakeData file without external lookup, use:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s6_lake_reservoir_config/setup_lake_data.py \
  --geodata outputs/hype_run/modelfiles/GeoData.txt \
  --output outputs/hype_run/modelfiles/LakeData.txt \
  --subbasins outputs/hype_run/subbasins/subbasins.shp
```

## Verification

- `LakeData.txt` and `DamData.txt` are in `modelfiles/`, alongside `GeoData.txt`.
- Any water class intended to behave as lake water has `special=2` in `GeoClass.txt`.
- If `GeoClass.txt` uses `special=2`, `LakeData.txt` exists and `GeoData.txt` has the corresponding `lakedataid`/lake fields expected by the generated file.
- Compare downstream discharge shape after s7; lake/dam routing should attenuate or regulate flows rather than leave the hydrograph unchanged.

## Traps

- `dt_s04`: water classes not marked `special=2` are treated as ordinary land, so `LakeData.txt` and `DamData.txt` have no effect.
- `dt_s01`: after `--update_geodata`, SLC fractions still must sum to 1.0; rerun `validate_geodata.py`.
- `dt_v01`: using one subbasin for a large basin means the outlet lake can over-attenuate the whole basin because all runoff passes through one outlet storage.

## Example

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s6_lake_reservoir_config/generate_lakedata.py \
  --geodata outputs/hype_run/modelfiles/GeoData.txt \
  --geoclass outputs/hype_run/modelfiles/GeoClass.txt \
  --output outputs/hype_run/modelfiles/LakeData.txt \
  --lat 32.4 \
  --lon 115.7 \
  --search_radius_km 100 \
  --update_geodata

python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s6_lake_reservoir_config/generate_damdata.py \
  --geodata outputs/hype_run/modelfiles/GeoData.txt \
  --output outputs/hype_run/modelfiles/DamData.txt \
  --dam_names "Meishan,Xianghongdian,Foziling"
```
