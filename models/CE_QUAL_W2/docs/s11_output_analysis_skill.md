# s11: Output Analysis and Visualization — Skill Document

## Purpose

Parse CE-QUAL-W2 output files and generate visualizations. The signature output is the **curtain plot**: a 2D longitudinal-vertical cross-section showing temperature (or other variables) from upstream to dam at different depths.

## Prerequisites

- [ ] CE-QUAL-W2 run completed successfully (s10)
- [ ] Output files exist: snp_*.opt, tsr_*.opt, spr_*.opt
- [ ] reservoir_grid.json available (for spatial coordinates)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Run directory | Path | s10 | Directory with output files |
| Grid JSON | File | s1 | Segment distances and layer elevations |

## Procedure

### Step 1: Parse output files

```bash
python tools/s11_output_analysis/parse_w2_output.py \
    --run_dir <run_dir> \
    --grid_json reservoir_grid.json \
    --output results_summary.json
```

This extracts:
- Snapshot data (2D temperature/velocity fields at key times)
- Time series data (temperature/DO at specific locations)
- Spreadsheet data (summary tables)

### Step 2: Generate curtain plot

```bash
python tools/s11_output_analysis/plot_w2_curtain.py \
    --run_dir <run_dir> \
    --grid_json reservoir_grid.json \
    --variable temperature \
    --output curtain_plot.png \
    --title "Reservoir Temperature Curtain"
```

Generates multi-panel plot with up to 4 snapshots (quarterly).

### Step 3: Generate time series

```bash
python tools/s11_output_analysis/plot_w2_timeseries.py \
    --run_dir <run_dir> \
    --output timeseries.png \
    --title "Reservoir Time Series"
```

### Step 4: Interpret results

Key things to check:
- **Thermal stratification**: Summer curtain should show warm surface layer, cool deep layer
- **Longitudinal gradient**: Upstream should be slightly different from dam (temperature, turbidity)
- **Seasonal cycle**: Summer warming, winter cooling, spring/fall mixing
- **Dam release temperature**: Should reflect withdrawal elevation and stratification

## Expected Outputs

| Output | Path | Description |
|--------|------|-------------|
| Summary JSON | `results_summary.json` | Parsed data statistics |
| Curtain plot | `curtain_plot.png` | 2D lon-vert temperature sections |
| Time series | `timeseries.png` | Temperature/DO at key locations |

## Validation Checks

1. Surface temperature range: 0-35 C (typical for most reservoirs)
2. Bottom temperature: should be cooler than surface in summer (stratification)
3. Seasonal amplitude: 15-30 C range for temperate reservoirs
4. Dam release temperature: should be intermediate (between surface and bottom)

## Common Pitfalls

| Pitfall | Triplet | Detection |
|---------|---------|-----------|
| No output to parse | dt_025 | results_summary shows 0 snapshots |
| Unrealistically warm everywhere | dt_001 | Cloud cover wrong (tenths vs fraction) |
| No stratification | dt_016/EXH2O | Light extinction too high or WSC too high |
