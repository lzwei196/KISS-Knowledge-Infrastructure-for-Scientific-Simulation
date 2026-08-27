# s5_postprocess

## Purpose

Export pySTEPS nowcast arrays into user-facing geospatial or tabular formats. This stage is implemented by `tools/s5_postprocess/export_nowcast.py` and converts the internal `nowcast.npz` output into NetCDF, GeoTIFF, or a domain-average CSV time series.

## Inputs

- `--nowcast_dir`: s3 output containing `nowcast.npz` and `nowcast_summary.json`.
- `--input_dir`: s1 output containing `metadata.json` for spatial reference and timestep.
- `--format`: `netcdf`, `geotiff`, or `csv`.
- Optional `--accumulate`: write precipitation depth in mm instead of rate in mm/h.

## Outputs

- NetCDF: `nowcast.nc`.
- GeoTIFF: one file per lead time, named `nowcast_ltNNN.tif`.
- CSV: `nowcast_timeseries.csv` with lead time, mean, max, p90, and wet fraction.
- `export_summary.json` listing format, unit, output files, and forecast shape.

## Procedure

Inspect the stage CLI:

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 tools/s5_postprocess/export_nowcast.py --help
```

Export a NetCDF rate forecast:

```bash
python3 tools/s5_postprocess/export_nowcast.py \
  --nowcast_dir /tmp/pysteps_case/s3_nowcast \
  --input_dir /tmp/pysteps_case/s1_data_import \
  --format netcdf \
  --output_dir /tmp/pysteps_case/s5_postprocess
```

Export accumulated GeoTIFFs when downstream consumers need depth in mm:

```bash
python3 tools/s5_postprocess/export_nowcast.py \
  --nowcast_dir /tmp/pysteps_case/s3_nowcast \
  --input_dir /tmp/pysteps_case/s1_data_import \
  --format geotiff \
  --accumulate \
  --output_dir /tmp/pysteps_case/s5_postprocess_geotiff
```

The `--accumulate` switch multiplies each rate frame by `timestep_min / 60.0`; it does not sum across lead times.

## Verification

Check the export summary:

```bash
python3 - <<'PY'
import json
from pathlib import Path
d = Path('/tmp/pysteps_case/s5_postprocess')
summary = json.loads((d / 'export_summary.json').read_text())
print(summary['format'], summary['unit'], summary['output_files'])
assert summary['output_files']
for f in summary['output_files']:
    assert Path(f).exists()
PY
```

For NetCDF exports, inspect the generated dataset with `ncdump -h /tmp/pysteps_case/s5_postprocess/nowcast.nc` if NetCDF command-line tools are installed.

## Traps

- `dt_pysteps_003`: accumulation requires multiplying mm/h by timestep hours. This tool does that per frame only when `--accumulate` is set.
- `dt_pysteps_011`: exceedance probability interpretation depends on mm/h thresholds; exported ensemble fields remain rates unless accumulated.
- `dt_pysteps_019`: map overlays can shift if `metadata['projection']` is wrong or missing. GeoTIFF export falls back to EPSG:4326 only when CRS parsing fails.
- `dt_pysteps_020`: hydrological grids, gauges, and catchments usually need reprojection or resampling before spatial joins.

## Example

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 tools/s5_postprocess/export_nowcast.py \
  --nowcast_dir /tmp/pysteps_case/s3_nowcast \
  --input_dir /tmp/pysteps_case/s1_data_import \
  --format csv \
  --output_dir /tmp/pysteps_case/s5_postprocess_csv
```

Expected product: `/tmp/pysteps_case/s5_postprocess_csv/nowcast_timeseries.csv` plus `export_summary.json`.
