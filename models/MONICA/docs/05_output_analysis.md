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

MONICA writes ONE BLOCK PER OUTPUT EVENT. Every block starts with a bare,
quoted section-label line (the event key: `"daily"`, `"monthly"`, `"yearly"`,
`"run"`, `"crop"`), then that block's own header rows and data, and blocks are
separated by a blank line. A crop/harvest-event file therefore looks like:

```
"crop"
CM-count;Crop;Yield;AbBiom;sowing;harvest
[];[];[kgDM ha-1];[kgDM ha-1];[];[]
1;wheat/winter wheat;3595.3;16690.9;1997-09-28;1998-07-02
```

and a daily block like:

```
"daily"
Date,Crop,Yield,LAI,Act_ET,Precip,Mois/1,Mois/2,...
,[kg ha-1],[m2 m-2],[mm],[mm],[m3 m-3],[m3 m-3],...
j:Date,j:Crop,j:Yield,j:LAI,...
1991-01-01,,0,0,0.5,0,...
```

- **Row 0**: section label (quoted event key) — NOT a header; a parser that
  takes line 0 as the header reads `columns=["crop"]` and loses every yield
  (triplet dt_27)
- **Row 1**: Column names (each block has its OWN header and separator)
- **Row 2**: Units in brackets
- **Row 3**: JSON references (j:, m:, c: prefixes) — optional
- **Row 4+**: Data rows (comma or semicolon separated), until a blank line or
  the next section label

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

### Metric families by obs_shape — what may be REPORTED, not only computed (2026-08-22, dt_32)

The dag (`dag.yaml` → `outputs.Yield.observability.comparable_obs_shapes`) fixes which metric FAMILIES are valid
per obs_shape, and the orchestrator's dag_driven_gate rejects a result whose `metrics` / `test_runs` row carries a
metric outside them:

| obs_shape                        | valid families                            | report on the row                                   | keep as aux only |
|----------------------------------|-------------------------------------------|-----------------------------------------------------|------------------|
| point_time_series (trials)       | magnitude_accuracy, temporal_pattern_match | pbias, rmse, nse, kge, r                            | —                |
| point_snapshot (one season)      | magnitude_accuracy                         | pbias                                               | —                |
| regional_aggregate_time_series   | magnitude_accuracy, trend_match            | pbias, rmse, trend_error, decadal_pbias, slope_ratio | nse, kge, r, r_detr (`aux_temporal_pattern_not_gate_valid`) |

`trend_error` = slope of (sim − obs) × (n − 1) / mean(obs); `decadal_pbias` = max |PBIAS| of the half-period means;
FAOSTAT / yearbook / GDHY / SPAM are regional aggregates (fresh weight, ÷0.88 — see SKILL.md Unit notes, dt_31).

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
