# Skill: Output Analysis and Validation

## Purpose

Parse MARRMoT simulation output into standardized CSV format, compute
validation metrics against observed streamflow, and generate diagnostic
visualizations. This skill covers post-processing, metric computation,
and result interpretation.

## Inputs

| Input                    | Source               | Format     | Unit          |
|--------------------------|----------------------|------------|---------------|
| Simulated timeseries     | `run_marrmot.py`     | CSV / JSON | mm/d          |
| Observed streamflow      | GRDC / local gauge   | CSV        | mm/d or m3/s  |
| Catchment area           | Metadata             | Scalar     | km2           |

## Outputs

| Output                   | Format     | Contents                            |
|--------------------------|------------|-------------------------------------|
| `results.csv`            | CSV        | Timestep, Q_sim, Q_obs (aligned)    |
| `validation.png`         | PNG        | Hydrograph + residuals + metrics    |
| Metrics JSON             | stdout     | NSE, KGE, PBIAS, RMSE, r           |

## Procedure

### Step 1: Load simulated data

```bash
python tools/parse_output.py --input run_output.json
```

The tool loads either:
- JSON from `run_marrmot.py` (follows `output_csv` path inside)
- Direct CSV with columns `timestep, Q_mm_d, Ea_mm_d`

### Step 2: Load and align observed data

If `--observed` is provided:

1. Read CSV with date and discharge columns
2. **Convert units if needed** (dt_010):
   - If observed Q is in m3/s: `Q_mm_d = Q_m3s * 86400 / (area_km2 * 1e6) * 1000`
   - Requires `--area-km2` and `--obs-unit m3_s`
3. Align time series (trim to shorter length)

### Step 3: Compute metrics

| Metric | Formula                                    | Perfect | Baseline |
|--------|--------------------------------------------|---------|----------|
| NSE    | 1 - SS_res / SS_tot                        | 1       | 0        |
| KGE    | 1 - sqrt((r-1)^2 + (alpha-1)^2 + (beta-1)^2) | 1   | ~-0.41   |
| r      | Pearson correlation                        | 1       | 0        |
| alpha  | std(sim) / std(obs)                        | 1       | -        |
| beta   | mean(sim) / mean(obs)                      | 1       | -        |
| PBIAS  | 100 * sum(sim-obs) / sum(obs)              | 0%      | -        |
| RMSE   | sqrt(mean((obs-sim)^2))                    | 0       | -        |

### Step 4: Interpret results

| Metric range     | Interpretation                              |
|-------------------|---------------------------------------------|
| NSE > 0.7         | Good — model captures dynamics well         |
| NSE 0.4 - 0.7     | Acceptable — captures main patterns         |
| NSE < 0.4         | Poor — consider different structure/params  |
| NSE < 0            | Worse than mean — check units or structure  |
| KGE > 0.5         | Good for daily streamflow                   |
| PBIAS -10% to 10% | Acceptable volume balance                   |
| PBIAS > 25%        | Large systematic bias — check units         |

### Step 5: Generate figure

```bash
python tools/parse_output.py \
  --input run_output.json \
  --observed observed_q.csv \
  --obs-unit mm_d \
  --output results.csv \
  --figure validation.png
```

Figure layout:
- **Top panel**: Hydrograph — observed (black) vs simulated (#2563EB blue)
- **Bottom panel**: Residuals (sim - obs) as bar chart
- **Metrics box**: Top-right corner of hydrograph panel

## Verification

| Check                    | Expected            | If fails                    |
|--------------------------|---------------------|-----------------------------|
| NSE > -1                 | Yes                 | Unit mismatch (dt_010)      |
| PBIAS within +/-50%      | Yes                 | Unit or parameter issue     |
| Q_sim >= 0 everywhere    | Yes                 | Numerical instability       |
| Sum(Q_sim) reasonable    | Within 2x of P-E   | Water balance problem       |
| Figure readable          | Yes                 | matplotlib import error     |

## Traps

- **dt_010**: Observed streamflow in m3/s compared directly to simulated
  mm/d. This produces NSE << -100 because the magnitudes differ by
  orders of magnitude. Always convert observed to mm/d first using
  catchment area.

- **Warm-up period**: The first year of simulation is unreliable because
  initial storages (S0) affect results. Exclude the first 365 days from
  metric computation by using `--warmup 365` or trimming manually.

- **Missing data**: NaN values in observed data must be masked before
  computing metrics. All metric functions in `parse_output.py` handle
  NaN masking automatically.

- **Scale mismatch**: MARRMoT simulates the entire catchment as a single
  lumped unit. Observed Q at a gauge reflects only the area upstream of
  that gauge. Ensure the catchment area used for unit conversion matches
  the gauged area, not total basin area.

## Example

```bash
# Full pipeline: parse + validate + figure
python tools/parse_output.py \
  --input run_output.json \
  --observed /data/grdc_daily.csv \
  --obs-col discharge_m3s \
  --obs-unit m3_s \
  --area-km2 1250 \
  --date-col date \
  --output results.csv \
  --figure validation.png

# Expected metrics output:
# {
#   "metrics": {
#     "NSE": 0.72,
#     "KGE": 0.78,
#     "r": 0.87,
#     "PBIAS": -5.3,
#     "RMSE": 1.23
#   }
# }
```
