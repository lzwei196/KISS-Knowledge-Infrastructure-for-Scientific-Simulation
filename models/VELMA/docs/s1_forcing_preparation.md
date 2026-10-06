# Stage 1: Forcing Preparation

**REAL engine:** build weather drivers with `tools/build_velma_weather_from_source.py --source cmfd|mswx|nasa_power --lat --lon --start-year --end-year --out-dir <input folder> --prefix <name>` (P mm/day, T deg C, one value per row; MSWX read serially). The Kelvin JSON below is for the Python SURROGATE only.

## Purpose
Convert gridded climate forcing into the daily basin-average JSON consumed by `tools/run_velma.py`. This KI expects precipitation in `mm/d`, air temperature in Kelvin, and incoming solar radiation in `W/m2`.

## Inputs
- CMFD or ERA5-style NetCDF files in a forcing directory.
- Basin polygon shapefile for masking.
- Year range in `YYYY-YYYY` form.
- Source variable names and units passed to `tools/convert_forcing_to_velma.py`.
- References: `SKILL.md`, `dag.yaml`, `docs/format_spec.yaml`, `docs/validation_convention.yaml`, and `diagnostics/triplets.yaml`.

## Outputs
- A forcing JSON file with `dates`, `prec_mm_d`, `temp_K`, `srad_Wm2`, `n_days`, unit metadata, conversion constants, and summary statistics. `filled_values` is always 0: no value or date is filled; a missing day or value stops the tool.
- With `--solar-mode unused` (for the native Java model, which reads P and T only) the file has no `srad_Wm2`. `tools/run_velma.py` needs radiation for PET and stops on such a file; it never puts a constant in its place.
- Only already-daily NetCDF sources are read. Sub-daily inputs must be checked and summed to days upstream (the tool does not sum 3-hourly values).
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

## Strict input contract

Every requested year must contain exactly one ordered daily record per date,
including leap days. Duplicate, missing, shifted or extra dates, absent variables,
missing annual files, NaN/Inf and negative precipitation or solar radiation fail.
Temperature must be within -100 to 70 Celsius after explicit unit conversion.
All selected raw cell values are checked before spatial averaging. Cell weights
are equal; polygons require a declared CRS and are reprojected to EPSG:4326.
All features are used. Zero covered cell centres is an error, not a bounding-box
fallback. Longitude/latitude coordinates in degrees are required.

No precipitation, temperature or radiation is interpolated or replaced. Genuine
zero values are retained, and forcing values are not rounded. Subdaily input and
`mm/3h` are rejected; validate the complete subdaily source and aggregate upstream.
A failed conversion exits nonzero and does not overwrite an existing output.
Successful output records input-file SHA256 hashes, units and `filled_values: 0`.

The default `--solar-mode required` serves the legacy Python approximation.
EPA's original Java model takes native P/T weather files with **Celsius**
temperatures. Explicit `--solar-mode unused` omits solar for this separate route;
export JSON Kelvin temperature to Celsius exactly once. No native Java runner or
native file exporter is installed by this converter repair. See the EPA links in
`SKILL.md`; do not treat Python preflight success as a native Java test.

## Verification
- The tool exits with `status: success`.
- `output.n_days` matches the requested year range exactly, with no date intersection or truncation.
- Check declared precipitation units against source metadata. Dry periods and real zero rain are valid; a climatological average does not authorize filling.
- `output.statistics.temp_mean_K` is in Kelvin, normally about 250-320 K.
- In required-solar mode, solar is finite nonnegative daily mean W/m2; real zero is preserved.
- The log contains no `[CRITICAL]` unit or mask warnings.

## Traps
- `dt_velma_001`: CMFD precipitation left as `kg/m2/s`, causing near-zero streamflow.
- `dt_velma_002`: 3-hourly precipitation handled as daily totals, inflating rainfall.
- `dt_velma_003`: Celsius temperatures passed to the legacy Python approximation, which subtracts 273.15 internally, collapsing PET and snowmelt.
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
