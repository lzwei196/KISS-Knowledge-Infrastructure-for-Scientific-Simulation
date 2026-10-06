# s1 Forcing Preparation

## Purpose

Convert gridded climate forcing into the JSON contract consumed by the KINEROS2 lumped daily runner. This KI expects daily basin-average precipitation in `mm/d` and daily mean temperature in `deg C`; `tools/convert_forcing_to_kineros2.py` performs the basin mask, unit conversion, plausibility checks, and JSON writing.

## Inputs

- A forcing directory containing NetCDF files matching the converter's `--file-pattern`.
- A basin boundary shapefile in the same coordinate system as the gridded data, normally EPSG:4326 for CMFD-style longitude/latitude grids.
- A year range such as `1980-1990`.
- Source variable names and units. The converter supports precipitation units `kg/m2/s`, `mm/d`, `m/d`, `mm/3h` and temperature units `K`, `C`, `F`.

## Outputs

- A forcing JSON file with `status`, `output.dates`, `output.prec_mm_d`, `output.temp_deg_c`, units, source units, summary statistics, and converter log messages.
- The downstream stages read this exact contract through `tools/run_kineros2.py::load_forcing`.

## Procedure

1. From the KI root, confirm the executable interface:

   ```bash
   python tools/convert_forcing_to_kineros2.py --help
   ```

2. Convert CMFD daily files to KINEROS2 forcing JSON:

   ```bash
   python tools/convert_forcing_to_kineros2.py \
     --forcing-dir /path/to/CMFD/Data_forcing_01dy_025deg \
     --shapefile /path/to/basin.shp \
     --years 1980-1990 \
     --prec-var prec \
     --temp-var temp \
     --prec-unit kg/m2/s \
     --temp-unit K \
     --file-pattern "{var}_CMFD_V0200_B-01_01dy_025deg_{year}01-{year}12_huai.nc" \
     --output work/forcing.json
   ```

3. Keep the generated JSON untouched. The runner expects `prec_mm_d` and `temp_deg_c`, not arbitrary aliases.

## Verification

Run:

```bash
python preflight_check.py
```

Then inspect the converter log in stdout or in `work/forcing.json`. A usable forcing file should report a nonzero timestep count, a realistic mean precipitation, and a mean temperature in degrees Celsius. If running manually, check the output structure with:

```bash
python -m json.tool work/forcing.json >/dev/null
```

## Traps

- `dt_kineros2_001`: CMFD precipitation left in `kg/m2/s` produces a nearly flat hydrograph because rainfall is 86400x too low.
- `dt_kineros2_002`: 3-hourly precipitation treated as daily totals makes runoff about 8x too high.
- `dt_kineros2_003`: Kelvin temperatures passed to Hamon PET create extreme evapotranspiration.
- `dt_kineros2_008`: Manually edited forcing JSON with keys such as `precip` or `temp` will fail in `tools/run_kineros2.py`.
- `dt_kineros2_023`: A shapefile CRS or overlap problem can produce zero or NaN basin-average precipitation.

## Example

For the Huai/Bengbu validation setup described in `SKILL.md`, use CMFD source units and the Huai filename pattern:

```bash
python tools/convert_forcing_to_kineros2.py \
  --forcing-dir /data/CMFD/Data_forcing_01dy_025deg \
  --shapefile /data/basins/huai_bengbu.shp \
  --years 1980-1990 \
  --prec-unit kg/m2/s \
  --temp-unit K \
  --output work/forcing_1980_1990.json
```
