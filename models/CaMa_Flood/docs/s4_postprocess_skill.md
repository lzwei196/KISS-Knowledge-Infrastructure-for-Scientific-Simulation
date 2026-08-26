# Stage 4: Post-process Output Skill

Thin wrapper for the preserved detailed note: [s4_postprocess.md](s4_postprocess.md).

## Purpose

Extract CaMa-Flood output variables at gauge coordinates or compute spatial summaries for flood variables, producing CSV-ready products for validation and downstream analysis.

## Inputs

- `tools/parse_cama_output.py`
- Output directory: `KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/`
- Output NetCDFs such as `o_outflw2003.nc` and `o_flddph2003.nc`
- Variable names from `SKILL.md` and `docs/format_spec.yaml`: `outflw`, `rivdph`, `sfcelv`, `flddph`, `fldfrc`, `rivsto`
- Optional observed discharge CSV for `--obs_csv`
- `docs/validation_convention.yaml`
- `diagnostics/triplets.yaml`

## Outputs

- Printed point statistics or spatial statistics.
- Optional point-extraction CSV from `--csv`.
- Optional spatial-stat CSV files when `--spatial_stats` is used.
- Optional NSE, PBIAS, KGE, and correlation metrics for `outflw` when `--obs_csv` is supplied.

## Procedure

Extract Bengbu discharge and flood depth at the documented gauge coordinate:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/parse_cama_output.py \
  --output_dir KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama \
  --variable outflw,flddph \
  --lat 32.95 --lon 117.35 \
  --start_year 2000 --end_year 2005 \
  --csv /tmp/discharge_bengbu.csv
```

Compute spatial flood-depth statistics for the 2003 flood year:

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

Confirm the output NetCDFs and parser products:

```bash
test -s KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/o_outflw2003.nc
test -s KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/o_flddph2003.nc
find KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama -maxdepth 1 -name 'o_*.nc' -printf '%f\n' | sed 's/^o_//; s/[0-9][0-9][0-9][0-9]\.nc$//' | sort -u
```

If a CSV was requested, check its header:

```bash
head /tmp/discharge_bengbu.csv
```

## Traps

- `dt_016`: first-year cold-start storage can degrade validation metrics; exclude the spin-up year or confirm restart files before scoring.
- `dt_017`: nearest latitude/longitude snapping can choose the wrong CaMa cell; formal gauge validation should match drainage area when possible.
- `dt_020`: validation must use `outflw` in `m3/s` for streamflow Q, not `rivdph`, `flddph`, `sfcelv`, or an unavailable `rivout` file.

## Example

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/parse_cama_output.py \
  --output_dir KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama \
  --variable outflw \
  --lat 32.95 --lon 117.35 \
  --start_year 2000 --end_year 2005
```

