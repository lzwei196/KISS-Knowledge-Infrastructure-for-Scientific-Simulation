# S8 Visualization

## Purpose

Create PNG diagnostics from the structured S7 results CSV: one hydrograph and water-level figure, and one breach-geometry evolution figure. These plots are for inspecting breach timing, peak discharge, drawdown, and geometry evolution after the validated model run.

## Inputs

- `--breach_csv`: CSV from `tools/s7_output/extract_breach_results.py`.
- `--output`: PNG path.
- Optional `--title` and `--json_output`.

## Outputs

- Hydrograph PNG from `plot_breach_hydrograph.py`.
- Breach-evolution PNG from `plot_breach_evolution.py`.
- Optional JSON metadata for each plot.

## Procedure

Plot breach discharge, spillway/gate flow, total discharge, and water levels:

```bash
python3 tools/s8_visualization/plot_breach_hydrograph.py \
  --breach_csv outputs/demo/demo_results.csv \
  --output outputs/demo/demo_hydrograph.png \
  --title "DLBreach demo hydrograph" \
  --json_output outputs/demo/hydrograph_plot.json
```

Plot breach bottom width, top width, bottom elevation, side slope, flow area, discharge, and cumulative volume:

```bash
python3 tools/s8_visualization/plot_breach_evolution.py \
  --breach_csv outputs/demo/demo_results.csv \
  --output outputs/demo/demo_evolution.png \
  --title "DLBreach demo breach evolution" \
  --json_output outputs/demo/evolution_plot.json
```

Use `docs/validation_convention.yaml` when interpreting hydrograph peak error, final width error, or reservoir drawdown diagnostics against observations.

## Verification

- Each plotting command returns `status: success`.
- PNG files exist and are non-empty.
- Hydrograph metadata includes `peak_q_annotation`.
- The input CSV header contains the exact S7 parser names.

```bash
test -s outputs/demo/demo_hydrograph.png
test -s outputs/demo/demo_evolution.png
```

## Traps

- `dt_022`: plotting tools require the CSV headers emitted by S7. Passing raw `casename.out` or a hand-edited CSV can trigger `KeyError` for fields such as `time_hr` or `breach_top_width_m`.
- `dt_018`: if extraction produced no valid rows, plotting cannot recover; fix S6/S7 first.

## Example

```bash
cd KISSPATH_KI_ROOT/DLBreach/knowledge_infrastructure
python3 tools/s8_visualization/plot_breach_hydrograph.py \
  --breach_csv outputs/example_case/example_case_results.csv \
  --output outputs/example_case/example_case_hydrograph.png \
  --json_output outputs/example_case/hydrograph_plot.json
```

