# Stage 2: Convert Forcing

## Purpose

Convert FLUXNET2015, CMFD, or MSWX meteorological forcing into the daily LPJ-GUESS analytic input table used by `tools/run_lpjguess.py`.

## Inputs

- `tools/convert_forcing_to_lpjguess.py`
- Source forcing:
  - FLUXNET2015 daily or monthly CSV, or
  - CMFD NetCDF directory, or
  - MSWX NetCDF directory
- For CMFD/MSWX only: `--lat`, `--lon`, `--start-year`, and `--end-year`
- Unit expectations documented in `SKILL.md` and `docs/format_spec.yaml`

## Outputs

A CSV with these columns:

- `date`
- `year`
- `month`
- `SW_IN` in `W/m2`
- `TA` in `deg C`
- `VPD` in `hPa`
- `P` in `mm/day`

This output is the `--forcing` input to `tools/run_lpjguess.py`.

## Procedure

Check the converter interface:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/convert_forcing_to_lpjguess.py --help
```

Convert a FLUXNET2015 daily file:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/convert_forcing_to_lpjguess.py \
  --source fluxnet \
  --input /path/to/FLX_SITE_FULLSET_DD.csv \
  --output /tmp/lpjguess_forcing.csv
```

Convert CMFD for one site and period:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/convert_forcing_to_lpjguess.py \
  --source cmfd \
  --input /path/to/cmfd_dir \
  --lat 40.48 \
  --lon 116.97 \
  --start-year 2000 \
  --end-year 2010 \
  --output /tmp/lpjguess_forcing.csv
```

Convert MSWX similarly with `--source mswx`. For source-specific unit handling, keep the rules in `SKILL.md` and `docs/format_spec.yaml` in view.

## Verification

After conversion:

```bash
python3 - <<'PY'
import pandas as pd
df = pd.read_csv("/tmp/lpjguess_forcing.csv")
print(df.columns.tolist())
print(df[["SW_IN", "TA", "VPD", "P"]].describe())
PY
```

Check that:

- `SW_IN`, `TA`, and `VPD` exist and are not mostly missing.
- `TA` is plausible Celsius, normally far below `100`.
- `VPD` is plausible hPa, typically `5-40` for daytime tower data.
- `P` is non-negative `mm/day`.
- The converter does not print `CRITICAL` unit warnings.

## Traps

- `dt_lpjguess_001`: CMFD/MSWX temperature is Kelvin; the converter subtracts `273.15`. If output `TA` is above `100`, the wrong source path or variable was used.
- `dt_lpjguess_002`: CMFD precipitation must become `mm/day` by multiplying kg/m2/s by `86400`; MSWX 3-hour precipitation must be daily-summed.
- `dt_lpjguess_003`: VPD must be hPa. If source VPD is kPa, multiply by `10`; if Pa, divide by `100`.
- `dt_lpjguess_007`: `tools/run_lpjguess.py` only consumes a flat CSV with `SW_IN`, `TA`, and `VPD`; raw driver NetCDF is not a valid direct runner input.

## Example

For a FLUXNET daily file:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/convert_forcing_to_lpjguess.py \
  --source fluxnet \
  --input /path/to/FLX_US-Ha1_FLUXNET2015_FULLSET_DD.csv \
  --output /tmp/us_ha1_forcing_lpjguess.csv
```

The resulting `/tmp/us_ha1_forcing_lpjguess.csv` is passed to stage 4 as `--forcing`.
