# s1 Lake Identification

## Purpose

Find the target lake in HydroLAKES when available and build the GLM hypsographic morphometry JSON used by s6. GLM requires bottom-to-top elevation and area arrays, basin dimensions, crest elevation, and lake coordinates.

## Inputs

- Lake name and/or coordinates from s0.
- Optional HydroLAKES shapefile at `KISSPATH_DATA/lakes/HydroLAKES_polys_v10.shp`.
- Manual lake attributes: surface area, maximum depth, average depth, elevation, coordinates, and name.
- Optional custom `H` and `A` arrays.
- Tools: `tools/s1_lake_identification/lookup_hydrolakes.py` and `tools/s1_lake_identification/build_morphometry.py`.

## Outputs

- HydroLAKES lookup JSON, usually `lake_lookup.json`, with lake area, depth, volume, elevation, and metadata.
- Morphometry JSON, usually `morphometry.json`, containing `crest_elev`, `bsn_vals`, `H`, `A`, `depth_max_m`, `surface_area_km2`, and `volume_mcm`.

## Procedure

1. Search HydroLAKES by coordinates or name:

```bash
python tools/s1_lake_identification/lookup_hydrolakes.py \
  --lat 46.0 --lon -89.7 --radius_km 10 \
  --output lake_lookup.json
```

2. Build morphometry from the lookup result:

```bash
python tools/s1_lake_identification/build_morphometry.py \
  --from_hydrolakes lake_lookup.json \
  --num_levels 15 \
  --output morphometry.json
```

3. If HydroLAKES is unavailable or too coarse, use manual parameters:

```bash
python tools/s1_lake_identification/build_morphometry.py \
  --area_km2 0.64 --depth_avg 6.1 --depth_max 18.3 \
  --elevation 320 --lat 46.0 --lon -89.7 --name "Sparkling" \
  --output morphometry.json
```

4. For surveyed bathymetry, provide GLM-ready bottom-to-top arrays:

```bash
python tools/s1_lake_identification/build_morphometry.py \
  --H "301,305,310,315,320" \
  --A "0,50000,200000,450000,637000" \
  --lat 46.0 --lon -89.7 --name "CustomLake" \
  --output morphometry.json
```

## Verification

- `morphometry.json` has `"status": "success"`.
- `H` is strictly increasing and `A` is nondecreasing.
- `bsn_vals` equals `len(H)` and `len(A)`.
- `A[0]` is near zero for a pointed bottom or explicitly reflects a flat-bottom trapezoid.
- `crest_elev` equals the final/top `H` value.

## Traps

- `dt_006`: reversed or non-monotonic `H`/`A` arrays crash GLM during layer setup.
- `dt_007`: fewer than about 10-15 depth-area levels gives crude volume and stratification.
- `dt_008`: `bsn_vals` must exactly match the number of `H` and `A` values.
- `dt_031`: a failed lake lookup for a requested river gauge usually means GLM is the wrong model.

## Example

```bash
python tools/s1_lake_identification/build_morphometry.py \
  --area_km2 188 --depth_avg 24 --depth_max 60 \
  --elevation 155 --lat 40.48 --lon 116.97 --name "Miyun Reservoir" \
  --num_levels 15 --output morphometry.json
```
