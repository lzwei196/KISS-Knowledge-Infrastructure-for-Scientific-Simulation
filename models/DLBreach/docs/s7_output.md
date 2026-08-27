# S7 Output And Coupling

## Purpose

Parse the raw DLBreach 13-column output into structured CSV/JSON and, when HydroCraft routing is required, inject breach plus spillway discharge into CaMa-Flood runoff at the first downstream cell.

## Inputs

- Raw `casename.out` from S6.
- For CaMa coupling, the structured CSV from `extract_breach_results.py`, a CaMa runoff NetCDF, downstream cell coordinates, and `cell_area_m2`.

## Outputs

- `CASE_results.csv` with headers such as `time_hr`, `breach_flow_m3s`, and `spillway_gate_flow_m3s`.
- `CASE_results.json` with records and summary statistics.
- Optional modified CaMa runoff NetCDF plus injection metadata.

## Procedure

Parse the DLBreach output:

```bash
python3 tools/s7_output/extract_breach_results.py \
  --output_file outputs/demo/demo.out \
  --format both \
  --output_dir outputs/demo \
  --output outputs/demo/extract.json
```

Inject into CaMa-Flood runoff for downstream routing:

```bash
python3 tools/s7_output/inject_breach_to_cama.py \
  --breach_csv outputs/demo/demo_results.csv \
  --cama_runoff_nc /path/to/cama_runoff.nc \
  --downstream_lat 34.9 \
  --downstream_lon 110.1 \
  --cell_area_m2 625000000 \
  --breach_start_day 0 \
  --output_nc outputs/demo/cama_runoff_with_breach.nc \
  --output outputs/demo/inject.json
```

Read `docs/model_couplings.yaml` for `coupling_dlbreach_to_cama_runoff`.

## Verification

- Extract step returns `status: success`.
- CSV header starts with the expected parser names.
- Summary contains non-null `peak_breach_q_m3s`, `peak_breach_time_hr`, and `total_outflow_volume_m3`.
- Injection step reports `status: success`, `n_days_affected`, and `total_breach_volume_m3`.

```bash
head -n 1 outputs/demo/demo_results.csv
```

## Traps

- `dt_018`: parser finds no 13-column rows. Check that S6 produced the current `casename.out` and that it is not empty or malformed.
- `dt_017`: inject at the first downstream CaMa cell, not necessarily the dam cell, and pass `cell_area_m2` in square meters.
- `dt_027`: avoid parsing stale output from a manual binary run; S6 deletes stale output before launching.

## Example

```bash
cd KISSPATH_KI_ROOT/DLBreach/knowledge_infrastructure
python3 tools/s7_output/extract_breach_results.py \
  --output_file outputs/example_case/example_case.out \
  --format both \
  --output_dir outputs/example_case \
  --output outputs/example_case/extract.json
```

