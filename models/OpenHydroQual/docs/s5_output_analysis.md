# S5: Output Analysis

## Purpose

Parse OpenHydroQual output files, extract time series for key variables,
compute performance metrics, and generate diagnostic plots for validation.

## Inputs

| Input              | Source        | Description                           |
|--------------------|---------------|---------------------------------------|
| output.txt         | Stage S4      | Model output CSV (all variables)      |
| observedoutput.txt | Stage S4      | Observation comparison output         |
| observed.csv       | Field data    | Measured data for validation          |

## Outputs

| Output              | Format | Description                                 |
|---------------------|--------|---------------------------------------------|
| results.csv         | CSV    | Extracted time series (clean format)        |
| validation.png      | PNG    | Time series plot with obs vs sim            |
| metrics.json        | JSON   | Performance metrics (NSE, RMSE, KGE, etc.)  |

## Procedure

### Step 1: Parse Output

```bash
python ki/tools/parse_output.py \
  --input Examples/Wet_pond/output.txt \
  --output results.csv
```

This reads the OHQ output CSV and lists all available variables.

### Step 2: Extract Specific Variables

```bash
python ki/tools/parse_output.py \
  --input Examples/Wet_pond/output.txt \
  --output results.csv \
  --variables "O2:concentration,DOM:concentration,NH3:concentration"
```

### Step 3: Generate Plot

```bash
python ki/tools/parse_output.py \
  --input Examples/Wet_pond/output.txt \
  --output results.csv \
  --variables "O2:concentration,DOM:concentration" \
  --plot validation.png
```

### Step 4: Compute Metrics (with observed data)

```bash
python ki/tools/parse_output.py \
  --input Examples/Wet_pond/output.txt \
  --observed field_data.csv \
  --output results.csv \
  --metrics \
  --plot validation.png
```

### Step 5: Interpret Metrics

| Metric | Perfect | Good    | Acceptable | Formula                              |
|--------|---------|---------|------------|--------------------------------------|
| NSE    | 1.0     | > 0.75  | > 0.5      | 1 - SS_res/SS_tot                    |
| KGE    | 1.0     | > 0.75  | > 0.5      | 1 - sqrt((r-1)^2+(a-1)^2+(b-1)^2)   |
| RMSE   | 0.0     | < 1 SD  | < 2 SD     | sqrt(mean((obs-sim)^2))              |
| PBIAS  | 0%      | < 10%   | < 25%      | 100 * sum(obs-sim)/sum(obs)          |
| R^2    | 1.0     | > 0.85  | > 0.7      | (cov/std_o*std_s)^2                  |

### Step 6: Diagnose Poor Performance

If metrics are poor, check:

1. **High RMSE + Low NSE**: Systematic bias. Check unit conversions.
2. **High PBIAS**: Over/underestimation. Check boundary conditions.
3. **Low R^2**: Wrong timing or dynamics. Check forcing data alignment.
4. **NSE < 0**: Model worse than mean. Fundamental setup error.

## Verification

- Output CSV has correct number of columns
- Time column is monotonically increasing
- No NaN/Inf values in extracted data
- Concentrations are non-negative
- Flow values are physically reasonable
- Plot shows expected temporal patterns

## Traps

| Trap                                    | Impact   | Prevention                        |
|-----------------------------------------|----------|-----------------------------------|
| Output column names change with config  | Degraded | Use substring matching            |
| Time in output is days, not hours       | Silent   | Convert when comparing to obs     |
| Concentration in g/m^3, obs in mg/L     | None     | g/m^3 = mg/L (same unit)          |
| Missing observations for metric calc    | Error    | Check obs file has matching vars  |
| Plot with too many variables            | Degraded | Select 3-5 key variables max      |
| Output file empty (solver diverged)     | Fatal    | Check solver settings             |

## Example

Full analysis pipeline for the Wet Pond model:

```bash
# 1. Parse and extract key variables
python ki/tools/parse_output.py \
  --input Examples/Wet_pond/output.txt \
  --output analysis/results.csv \
  --variables "O2:concentration,DOM:concentration,NH3:concentration,NOx:concentration" \
  --plot analysis/wetpond_timeseries.png

# 2. Check output JSON
# Expected: stats for each variable showing reasonable ranges
# O2: 0-12 g/m^3, DOM: 0-50 g/m^3, NH3: 0-5 g/m^3, NOx: 0-10 g/m^3

# 3. If validation data available
python ki/tools/parse_output.py \
  --input Examples/Wet_pond/output.txt \
  --observed field_observations.csv \
  --output analysis/validated.csv \
  --metrics \
  --plot analysis/validation.png
```

### Interpreting Wet Pond Results

Expected behavior over 100 days:
- **DOM**: Should decrease along the treatment train (aerobic decomposition)
- **O2**: Should be maintained by atmospheric exchange, with diurnal variation
- **NH3**: Should decrease via nitrification (converted to NOx)
- **NOx**: Should decrease in anoxic sediment zones (denitrification)
- **Flow**: Should show response to inflow hydrograph at the weir outlet
- **Evapotranspiration**: Should show seasonal pattern if multi-year
