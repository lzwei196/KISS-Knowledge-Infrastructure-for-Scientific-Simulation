# Stage 5: Output Analysis

## Purpose

Parse the MONICA multi-header CSV output, extract clean timeseries, compute
summary statistics, and compare with observed data using domain-appropriate
metrics for crop model evaluation.

## Inputs

| File         | Description                                   |
|--------------|-----------------------------------------------|
| out.csv      | MONICA output file (multi-header format)      |
| observed.csv | (Optional) Observed data for comparison       |

## Outputs

| File             | Description                              |
|------------------|------------------------------------------|
| timeseries.csv   | Clean CSV with date + selected variables |
| summary.json     | Summary stats (yield, ET, N leaching)    |
| validation.png   | (Optional) Comparison figure             |

## MONICA Output Format

MONICA outputs have 3–4 header rows before data:

```
Date,Crop,Yield,LAI,Act_ET,Precip,Mois/1,Mois/2,...
,[kg ha-1],[m2 m-2],[mm],[mm],[m3 m-3],[m3 m-3],...
j:Date,j:Crop,j:Yield,j:LAI,...
1991-01-01,,0,0,0.5,0,...
```

- **Row 1**: Column names
- **Row 2**: Units in brackets
- **Row 3**: JSON references (j:, m:, c: prefixes)
- **Row 4+**: Data rows (comma or semicolon separated)

## Procedure

1. **Parse headers** — detect separator, extract column names and units
2. **Skip metadata rows** — identify where data starts (rows with j:/m:/c: prefix)
3. **Extract timeseries** — convert numeric columns to floats
4. **Compute summary** — yield, total ET, N leaching, mean soil moisture
5. **Compare with observed** — match dates, compute metrics
6. **Generate figures** — timeseries plots, scatter plots

## Evaluation Metrics

| Metric | Formula                                    | Ideal | Description                    |
|--------|--------------------------------------------|-------|--------------------------------|
| RMSE   | √(Σ(obs-sim)²/n)                         | 0     | Root mean square error         |
| R²     | 1 - SS_res/SS_tot                         | 1     | Coefficient of determination   |
| PBIAS  | 100 × Σ(sim-obs)/Σobs                    | 0%    | Percent bias                   |
| NSE    | 1 - Σ(obs-sim)²/Σ(obs-mean)²             | 1     | Nash-Sutcliffe efficiency      |
| d      | 1 - Σ(obs-sim)²/Σ(|sim-mean|+|obs-mean|)²| 1    | Willmott index of agreement    |

### Performance ratings for crop models (after Jamieson et al. 1991)

| Rating      | RMSE (yield)       | R²    | PBIAS     |
|-------------|-------------------|-------|-----------|
| Excellent   | < 10% of mean     | > 0.9 | < ±10%    |
| Good        | 10–20% of mean    | > 0.7 | ±10–20%   |
| Fair        | 20–30% of mean    | > 0.5 | ±20–30%   |
| Poor        | > 30% of mean     | < 0.5 | > ±30%    |

## Key Output Variables to Check

### Crop variables (sanity ranges)

| Variable | Expected range           | Red flag if                    |
|----------|--------------------------|--------------------------------|
| Yield    | 2000–12000 kg DM ha⁻¹   | > 20000 (radiation unit error) |
| LAI      | 0–8 m² m⁻²              | > 12 (N surplus)               |
| Height   | 0–2.5 m                  | > 3.0 (parameter error)        |
| Stage    | 0–7                      | Stuck at 0 (no emergence)      |
| TempSum  | 0–3000 °Cd               | Not accumulating               |

### Water balance (should close)

| Variable    | Check                                        |
|-------------|----------------------------------------------|
| Precip      | Should match input climate.csv               |
| Act_ET      | 200–800 mm yr⁻¹ for temperate crops         |
| Recharge    | Precip - ET - ΔS (approximately)             |
| RunOff      | Small unless heavy rainfall events           |

### Nitrogen balance

| Variable    | Expected range          | Red flag if              |
|-------------|------------------------|--------------------------|
| NLeach      | 5–80 kg N ha⁻¹ yr⁻¹   | > 200 (N deposition err) |
| Denit       | 1–30 kg N ha⁻¹ yr⁻¹   | > 100                    |
| SumNUp      | 100–250 kg N ha⁻¹      | < 50 (no crop growth)    |

## Verification

- [ ] Output file parsed without errors
- [ ] All requested columns present
- [ ] Date range matches simulation period
- [ ] Yield values physically plausible
- [ ] Water balance approximately closes
- [ ] Metrics computed if observed data provided

## Traps

| ID  | Symptom                      | Cause                                 | Fix                          |
|-----|------------------------------|---------------------------------------|------------------------------|
| —   | Parser fails on header rows  | Multi-header format not handled       | Skip rows with j:/m: prefix  |
| —   | All values are empty strings | Wrong separator in parser             | Auto-detect ; vs , vs tab    |
| —   | Date mismatch with observed  | Different date formats                | Standardise to YYYY-MM-DD    |
| —   | PBIAS > 100%                 | Unit mismatch (sim vs obs)            | Check both use same units    |

## Example

```bash
# Parse output and compute summary
python parse_monica_output.py \
    --input out.csv --output-dir ./parsed/

# Compare with observed yield data
python parse_monica_output.py \
    --input out.csv --output-dir ./parsed/ \
    --observed obs_yield.csv --obs-col yield_kgha --sim-col Yield \
    --metric rmse r2 pbias nse
```
