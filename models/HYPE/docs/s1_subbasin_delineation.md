# s1_subbasin_delineation

## Purpose

Delineate the HYPE subbasin domain and MAINDOWN routing topology from a basin boundary and outlet location. This stage creates the subbasin geometry that later stages use for SLC fractions, forcing extraction, GeoData generation, and outlet detection.

## Inputs

- Basin boundary shapefile: `--shp`
- Outlet latitude and longitude: `--outlet_lat`, `--outlet_lon`
- Target number of subbasins: `--n_subbasins`
- Optional topology validation input after generation: `maindown.csv` or `GeoData.txt`

## Outputs

- `subbasins.shp` and sidecar shapefile files in the requested output directory
- `maindown.csv` with `SUBID` to `MAINDOWN` routing
- Topology validation pass/fail report from `validate_topology.py`

## Procedure

Run the KI tool, not a custom GIS script:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s1_subbasin_delineation/delineate_subbasins.py \
  --shp data/shp/basin_shp/basin.shp \
  --outlet_lat 31.1 \
  --outlet_lon 117.1 \
  --n_subbasins 10 \
  --output outputs/hype_run/subbasins/
```

Validate the topology immediately:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s1_subbasin_delineation/validate_topology.py \
  --csv outputs/hype_run/subbasins/maindown.csv
```

## Verification

- `outputs/hype_run/subbasins/subbasins.shp` exists and has one `SUBID` per subbasin.
- `outputs/hype_run/subbasins/maindown.csv` has one outlet row with `MAINDOWN=0`.
- `validate_topology.py` exits successfully before `s4_geodata_generation`.
- For large basins, the subbasin count is high enough to avoid a lumped one-subbasin routing setup.

## Traps

- `dt_s10`: subbasin polygons overlap or leave gaps, so total subbasin area no longer matches basin area and discharge is silently biased.
- `dt_r05`: MAINDOWN cycles make routing invalid; break cycles before writing `GeoData.txt`.
- `dt_v01`: a one-subbasin setup for basins larger than about 10,000 km2 removes HYPE's internal routing attenuation and overpredicts peaks.

## Example

For a Bengbu-style semi-distributed run:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s1_subbasin_delineation/delineate_subbasins.py \
  --shp data/shp/basin_shp/bengbu.shp \
  --outlet_lat 32.4 \
  --outlet_lon 115.7 \
  --n_subbasins 10 \
  --output outputs/hype_run/subbasins/

python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s1_subbasin_delineation/validate_topology.py \
  --csv outputs/hype_run/subbasins/maindown.csv
```
