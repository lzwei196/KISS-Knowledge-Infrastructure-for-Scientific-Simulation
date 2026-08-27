# S2 Dam Inventory

## Purpose
Find candidate GRanD dams inside a basin boundary so later stages can build Pywr reservoir storage from real dam attributes. This stage is implemented by `../tools/s2_dam_inventory/find_dams_in_basin.py`.

## Inputs
- Basin boundary as either `--shp` shapefile or `--grid` VIC basin grid NetCDF.
- GRanD allocated CSV: `model/cmf_v420_pkg/map/data/GRanD_allocated.csv` as documented in `../SKILL.md`.
- Tool: `../tools/s2_dam_inventory/find_dams_in_basin.py`
- Optional filters: `--buffer_km`, `--min_capacity_mcm`

## Outputs
- JSON with `status`, basin metadata, `dams_found`, and sorted `dams`.
- Each dam record includes fields used downstream, including `name`, `capacity_mcm`, `dam_height_m`, `lat`, `lon`, `grand_id`, and `upstream_area_km2`.

## Procedure
Run from the HydroCraft project root or provide absolute paths:

```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"
GRAND=model/cmf_v420_pkg/map/data/GRanD_allocated.csv

"$PYWR_PYTHON" "$KI/tools/s2_dam_inventory/find_dams_in_basin.py" \
  --shp data/shp/bengbu_shp/bengbu_clip.shp \
  --grand "$GRAND" \
  --min_capacity_mcm 10 \
  --output /tmp/pywr_dams.json
```

For a VIC grid bounding box:

```bash
"$PYWR_PYTHON" "$KI/tools/s2_dam_inventory/find_dams_in_basin.py" \
  --grid outputs/bengbu_1980-1990_025deg/vic_temp/grid/grid_bengbu_1980-1990_025deg_025deg.nc \
  --grand "$GRAND" \
  --output /tmp/pywr_dams.json
```

## Verification
- The command exits `0` when dams are found. Exit `1` with `status: NO_DAMS` is a valid workflow decision point, not a parser failure.
- Check `dams_found > 0` before running S3.
- Check selected dams have non-null `capacity_mcm`, `lat`, and `lon`.
- Confirm large reservoirs sort first because the script sorts by `capacity_mcm` descending.

## Traps
- `dt_pywr_014`: GRanD capacity is `CAP_MCM`; S3 must convert it to Pywr `m3` with `* 1e6`.
- A missing basin shapefile, grid file, or GRanD CSV causes this tool to return JSON with an `error` and exit `2` or `3`; fix the path before continuing.
- `status: NO_DAMS` means skip Pywr for that basin unless a manual dam is supplied to S3.

## Example
```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"
"$PYWR_PYTHON" "$KI/tools/s2_dam_inventory/find_dams_in_basin.py" \
  --shp data/shp/bengbu_shp/bengbu_clip.shp \
  --grand model/cmf_v420_pkg/map/data/GRanD_allocated.csv \
  --output /tmp/pywr_dams.json
```
