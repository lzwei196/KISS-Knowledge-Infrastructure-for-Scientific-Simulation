# s8_output_analysis

## Purpose

Parse HYPE result files, compute discharge metrics, create plots, and compare HYPE discharge against VIC output or observations. This stage turns `time*.txt` files into reviewable CSVs, metrics, and figures.

## Inputs

- HYPE `resultdir/` from s7
- Optional `GeoData.txt` next to `resultdir/` for outlet autodetection
- Optional observed discharge file
- Optional VIC routing output for cross-model comparison
- Outlet SUBID when not autodetected

## Outputs

- Discharge CSV such as `outputs/hype_run/discharge.csv`
- Plot PNG such as `outputs/hype_run/discharge_plot.png`
- VIC-HYPE comparison PNG
- Printed NSE, KGE, PBIAS, RMSE, and sample count when observations are available

## Procedure

Parse HYPE discharge:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s8_output_analysis/parse_hype_output.py \
  --result_dir outputs/hype_run/resultdir/ \
  --output_csv outputs/hype_run/discharge.csv \
  --outlet_subid 3 \
  --variable cout
```

Plot discharge:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s8_output_analysis/plot_hype_results.py \
  --result_dir outputs/hype_run/resultdir/ \
  --outlet_subid 3 \
  --title "HYPE Simulation" \
  --output outputs/hype_run/discharge_plot.png
```

Compare VIC and HYPE:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s8_output_analysis/compare_vic_hype.py \
  --vic_discharge outputs/vic_run/routing_param/rout_out/station.day \
  --hype_result_dir outputs/hype_run/resultdir/ \
  --hype_outlet_subid 3 \
  --obs_file data/obs/basin/observed.txt \
  --output outputs/comparison/vic_hype_comparison.png
```

## Verification

- `parse_hype_output.py` reports the parsed date range and outlet summary.
- Outlet SUBID exists as a column in `timeCOUT.txt`.
- CSV and PNG outputs are created.
- If comparing to observations, there are at least 10 overlapping valid dates before interpreting metrics.

## Traps

- `dt_c01`: VIC and HYPE differ by 2-5x because they use different basin area, forcing period, or PET assumptions.
- `dt_c02`: HYPE discharge is much lower than VIC because daily precipitation was averaged rather than summed in s3.
- `dt_s02`: discharge scale is wrong because `GeoData.txt` area is in km2 rather than m2.
- `dt_v02`: zero discharge can persist through several clean HYPE exits; inspect forcing totals, streamdepth, and SLC fractions before trusting plots.

## Example

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s8_output_analysis/parse_hype_output.py \
  --result_dir outputs/hype_run/resultdir/ \
  --output_csv outputs/hype_run/discharge.csv \
  --outlet_subid 1 \
  --obs_file data/obs/basin/observed.txt

python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s8_output_analysis/plot_hype_results.py \
  --result_dir outputs/hype_run/resultdir/ \
  --outlet_subid 1 \
  --title "Bengbu HYPE Simulation" \
  --output outputs/hype_run/discharge_plot.png
```
