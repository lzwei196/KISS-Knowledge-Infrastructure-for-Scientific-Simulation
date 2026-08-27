# s1 Forcing Preparation

## Purpose

Convert lake observation data into the forcing JSON consumed by the WASP analytic reimplementation. This stage uses `tools/convert_forcing_to_wasp.py` to clean WQP/NLA temperature, dissolved oxygen, chlorophyll-a, phosphorus, Secchi, and profile observations into model units: temperature in deg C, dissolved oxygen in mg/L, chlorophyll-a and total phosphorus in ug/L, depth in m, and day of year as 1-366.

## Inputs

- `tools/convert_forcing_to_wasp.py`
- Optional WQP lake directory passed with `--wqp-dir`
- Optional WQP profile CSV passed with `--profile-csv`
- Optional NLA profile CSV passed with `--nla-csv`
- Optional NLA chemistry CSV passed with `--nla-chem-csv`
- Unit overrides: `--temp-unit C|F|K|auto` and `--depth-unit m|ft|cm|auto`
- Temporal filters: `--min-year` and `--max-year`

WQP CSVs must use the full WQP-style columns expected by the tool, especially `ActivityStartDate`, `ResultMeasureValue`, and the WQP depth/status columns when available.

## Outputs

- A JSON file with `status`, `model`, `output`, and `log`
- `output.temperature`, `output.do`, `output.chla`, `output.tp`, and `output.secchi` record lists when matching files are present
- `output.profiles`, `output.nla_profiles`, and `output.nla_chemistry` when profile or chemistry sources are supplied
- `output.stats` with record counts, ranges, dates, and depth coverage

## Procedure

Run from the KI root:

```bash
python preflight_check.py
python tools/convert_forcing_to_wasp.py \
  --wqp-dir /path/to/WQP/Lake_Erie_Central \
  --temp-unit auto \
  --depth-unit auto \
  --min-year 2005 \
  --max-year 2020 \
  --output /tmp/wasp_forcing.json
```

For a quick CLI smoke test using the existing tool path:

```bash
tmp="$(mktemp -d)"
mkdir -p "$tmp/wqp"
printf 'ActivityStartDate,ResultMeasureValue,ActivityDepthHeightMeasure/MeasureValue,ResultStatusIdentifier\n2020-07-15,20.5,1,Accepted\n2020-08-15,22.0,1,Accepted\n' > "$tmp/wqp/temperature_water.csv"
python tools/convert_forcing_to_wasp.py --wqp-dir "$tmp/wqp" --temp-unit C --depth-unit m --output "$tmp/forcing.json"
```

Use `docs/format_spec.yaml` for the accepted forcing variable names and units.

## Verification

- The command exits 0 and writes the requested JSON file.
- The JSON has `status: success` or `status: warning`; `status: error` means the forcing file was not produced.
- Check `output.stats.temperature.mean` is plausible for lake water in deg C.
- Check `output.stats.do.mean` is between 0 and 20 if DO records were supplied.
- Check records have `date`, `value`, and `doy`; profile records should have `depth_m`.

## Traps

- `dt_wasp_001`: WQP temperature in Fahrenheit produces surface temperatures above 40 C.
- `dt_wasp_002`: Kelvin input is double-shifted by the Benson-Krause calculation downstream.
- `dt_wasp_003` and `dt_wasp_004`: DO percent saturation or ug/L values are not valid mg/L forcing.
- `dt_wasp_005`: WQP profile depths in feet make observations appear below the lake bottom.
- `dt_wasp_007` and `dt_wasp_008`: WQP narrow-format or unexpected `CharacteristicName` values can leave arrays empty.
- `dt_wasp_018`: rejected or preliminary WQP records depress calibration skill.
- `dt_wasp_025`: chlorophyll-a in mg/L must be converted to ug/L before TSI.

## Example

```bash
python tools/convert_forcing_to_wasp.py \
  --wqp-dir /data/WQP/Lake_Erie_Central \
  --profile-csv /data/WQP/Lake_Erie_Central/discrete_profiles.csv \
  --temp-unit auto \
  --depth-unit auto \
  --output /tmp/erie_forcing.json
```

