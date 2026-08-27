# Stage 1: Forcing Preparation

## Purpose
Convert gridded climate forcing into the daily basin-average JSON consumed by `tools/run_velma.py`. This KI expects precipitation in `mm/d`, air temperature in Kelvin, and incoming solar radiation in `W/m2`.

## Inputs
- CMFD or ERA5-style NetCDF files in a forcing directory.
- Basin polygon shapefile for masking.
- Year range in `YYYY-YYYY` form.
- Source variable names and units passed to `tools/convert_forcing_to_velma.py`.
- References: `SKILL.md`, `dag.yaml`, `docs/format_spec.yaml`, `docs/validation_convention.yaml`, and `diagnostics/triplets.yaml`.

## Outputs
- A forcing JSON file with `dates`, `prec_mm_d`, `temp_K`, `srad_Wm2`, `n_days`, unit metadata, conversion constants, and summary statistics.
- Tool status JSON written to the requested output path and a console summary with warnings.

## Procedure
Run from the KI root:

```bash
python tools/convert_forcing_to_velma.py \
  --forcing-dir /path/to/CMFD/Data_forcing_01dy_025deg \
  --shapefile /path/to/basin.shp \
  --years 1980-1990 \
  --prec-var prec \
  --temp-var temp \
  --srad-var srad \
  --prec-unit kg/m2/s \
  --temp-unit K \
  --srad-unit W/m2 \
  --output forcing.json
```

Check the script interface when source filenames differ:

```bash
python tools/convert_forcing_to_velma.py --help
```

Use `docs/format_spec.yaml` for the expected JSON fields and `dag.yaml` for the forcing boundary: `prec_mm_d`, `temp_K`, and `srad_Wm2`.

## Verification
- The tool exits with `status: success`.
- `output.n_days` matches the requested year range after date alignment.
- `output.statistics.prec_mean_mm_d` is normally in the 1-10 mm/d range for humid basins and is not near zero.
- `output.statistics.temp_mean_K` is in Kelvin, normally about 250-320 K.
- `output.statistics.srad_mean_Wm2` is a daily mean radiation value, normally about 50-400 W/m2.
- The log contains no `[CRITICAL]` unit or mask warnings.

## Traps
- `dt_velma_001`: CMFD precipitation left as `kg/m2/s`, causing near-zero streamflow.
- `dt_velma_002`: 3-hourly precipitation handled as daily totals, inflating rainfall.
- `dt_velma_003`: Celsius temperatures passed to a model that subtracts 273.15 internally, collapsing PET and snowmelt.
- `dt_velma_004`: solar radiation unit confusion causing PET to become physically unreasonable.
- `dt_velma_008` and `dt_velma_009`: forcing JSON keys or NetCDF variable names do not match the converter.
- `dt_velma_019` and `dt_velma_020`: shapefile CRS or grid overlap leaves too few selected cells.

## Example
For Bengbu-style CMFD forcing documented in `SKILL.md`:

```bash
python tools/convert_forcing_to_velma.py \
  --forcing-dir /data/CMFD/Data_forcing_01dy_025deg \
  --shapefile /data/basins/bengbu.shp \
  --years 1980-1990 \
  --prec-unit kg/m2/s \
  --temp-unit K \
  --srad-unit W/m2 \
  --output forcing_bengbu_1980_1990.json
```
