# Stage 4: Post-process Output

## Purpose

Extract CaMa-Flood output variables at gauge coordinates or compute spatial statistics for flood variables, then write CSV products for validation and downstream analysis.

## Inputs

- `tools/parse_cama_output.py`
- CaMa output directory containing `o_{variable}{year}.nc`
- Variables such as `outflw`, `rivdph`, `sfcelv`, `flddph`, `fldfrc`, or `rivsto`
- For point extraction: `--lat` and `--lon`
- Optional observed discharge CSV for comparison with `--obs_csv`
- Validation conventions in `docs/validation_convention.yaml`
- Output variable definitions in `docs/format_spec.yaml`

## Outputs

- Printed point or spatial statistics
- Optional CSV time series from `--csv`
- Optional spatial-stat CSV files when `--spatial_stats` is used
- Optional NSE, PBIAS, KGE, and correlation metrics when `--obs_csv` is provided for `outflw`

## Procedure

Extract Bengbu discharge at a point:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/parse_cama_output.py \
  --output_dir KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama \
  --variable outflw \
  --lat 32.95 --lon 117.35 \
  --start_year 2000 --end_year 2005 \
  --csv /tmp/discharge_bengbu.csv
```

Compute spatial flood-depth statistics:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/parse_cama_output.py \
  --output_dir KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama \
  --variable flddph \
  --start_year 2003 --end_year 2003 \
  --spatial_stats \
  --csv /tmp/bengbu_flood_stats.csv
```

## Verification

Confirm the requested files exist before parsing:

```bash
test -s KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/o_outflw2003.nc
test -s KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/o_flddph2003.nc
```

List available output variables in a directory:

```bash
find KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama -maxdepth 1 -name 'o_*.nc' -printf '%f\n' | sed 's/^o_//; s/[0-9][0-9][0-9][0-9]\.nc$//' | sort -u
```

Check the CSV:

```bash
head /tmp/discharge_bengbu.csv
```

## Traps

- `dt_017`: nearest-lat/lon gauge snap may select the wrong CaMa cell; the parser warns when the nearest cell is more than 30 km away.
- `dt_020`: wrong output variable selected for validation. Use `outflw` in `m3/s` for streamflow Q; do not compare `rivdph`, `flddph`, or `sfcelv` to discharge observations.
- `dt_016`: first-year cold-start storage can degrade validation metrics. Exclude spin-up years or confirm restart files before scoring.

## Example

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/parse_cama_output.py \
  --output_dir KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama \
  --variable outflw,flddph \
  --lat 32.95 --lon 117.35 \
  --start_year 2000 --end_year 2005
```
