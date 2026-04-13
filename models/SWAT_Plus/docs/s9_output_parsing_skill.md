# Output Parsing and Analysis — Skill Document

> **Stage ID**: s9_output_parsing
> **Pipeline order**: 9 of 9
> **Depends on**: s8_model_execution

## Purpose

Parse SWAT+ output files to extract simulated discharge, sediment, and nutrient loads at the basin outlet. Compare with observed data to evaluate model performance using standard metrics (NSE, PBIAS, KGE). Verify mass balance closure for water and nutrients. This stage determines whether the model is scientifically valid or needs calibration adjustments (return to S6).

## Prerequisites

Before starting this stage, verify:

- [ ] SWAT+ simulation completed without errors (S8)
- [ ] Output files exist in TxtInOut (channel_sd_day.txt, basin_wb_day.txt, etc.)
- [ ] Observed discharge data available (if evaluating performance)
- [ ] Know which channel ID corresponds to the basin outlet

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| channel_sd_day.txt | file | S8 output | Channel discharge and water quality |
| basin_wb_day.txt | file | S8 output | Basin water balance |
| basin_nb_day.txt | file | S8 output | Basin nutrient balance |
| Observed discharge | file | Gauging station | For performance comparison |
| Outlet channel ID | number | From S1 connectivity | Which channel is the outlet |

## Procedure

### Step 1: Parse channel_sd output for discharge

```bash
python tools/s9/parse_channel_output.py
```

channel_sd_day.txt format:
```
 jday        mon         day         yr          unit        gis_id      name             ...   flo_in       flo_out      sed_in       sed_out      orgn_in      orgn_out     ...
 1           1           1           2000        1           1           cha001           ...   0.500        0.480        0.010        0.009        0.001        0.001        ...
```

Key variables:
- `flo_out`: Outflow discharge (m3/s) — primary calibration target
- `sed_out`: Sediment load leaving channel (tons)
- `orgn_out`: Organic nitrogen (kg)
- `sedp_out`: Sediment-bound phosphorus (kg)
- `no3_out`: Nitrate nitrogen (kg)
- `solp_out`: Soluble phosphorus (kg)

Filter for the outlet channel: `unit == outlet_channel_id` and `gis_id == outlet_gis_id`.

**Expected result**: Time series of daily discharge at the outlet.

### Step 2: Parse basin water balance

```bash
python tools/s9/parse_basin_output.py
```

basin_wb_day.txt key variables:
- `precip`: Precipitation (mm)
- `snofall`: Snowfall (mm)
- `snomlt`: Snowmelt (mm)
- `surq_gen`: Surface runoff generated (mm)
- `latq`: Lateral flow (mm)
- `wateryld`: Total water yield (mm)
- `perc`: Percolation to groundwater (mm)
- `et`: Evapotranspiration (mm)
- `sw_final`: Final soil water content (mm)

**Expected result**: Daily basin water balance components.

### Step 3: Compare with observed discharge

Align simulated and observed time series by date. Exclude warmup period.

```bash
python tools/s9/compute_performance_metrics.py
```

Performance metrics:
- **NSE** (Nash-Sutcliffe Efficiency): 1 = perfect, 0 = mean prediction, <0 = worse than mean
- **PBIAS** (Percent Bias): 0 = no bias, positive = underestimation, negative = overestimation
- **KGE** (Kling-Gupta Efficiency): 1 = perfect, considers correlation + variability + bias
- **R2** (Coefficient of determination): 0-1, measures linear correlation
- **RMSE** (Root Mean Square Error): 0 = perfect, same units as discharge

Moriasi et al. (2007) performance ratings:
| Rating | NSE | PBIAS (%) | RSR |
|--------|-----|-----------|-----|
| Very Good | > 0.75 | < 10 | < 0.50 |
| Good | 0.65-0.75 | 10-15 | 0.50-0.60 |
| Satisfactory | 0.50-0.65 | 15-25 | 0.60-0.70 |
| Unsatisfactory | < 0.50 | > 25 | > 0.70 |

**Expected result**: Performance metrics with ratings.

### Step 4: Check mass balance

```bash
python tools/s9/check_mass_balance.py
```

Water balance check (annual or multi-year average):
```
Precip = ET + Surface_Runoff + Lateral_Flow + Percolation + Delta_Storage
Error = |LHS - RHS| / Precip * 100
```

Acceptable error: < 5% for water balance, < 10% for nutrient balance.

**If this fails**: See diagnostic triplets dt_010, dt_015.

### Step 5: Generate visualization

Create time series plots of:
- Simulated vs observed discharge (if observed available)
- Monthly water balance components (bar chart)
- Annual nutrient loads (if water quality enabled)

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Discharge time series | JSON or CSV | Covers simulation period minus warmup |
| Performance metrics | JSON | NSE, PBIAS, KGE, R2, RMSE computed |
| Water balance check | JSON | Error < 5% |
| Nutrient balance check | JSON | Error < 10% |

## Validation Checks

1. **Discharge non-negative**: All flo_out values >= 0.
   - If negative: Numerical instability. Check time step and routing parameters.

2. **Mass balance closure**: Water balance error < 5%.
   - If >5%: See diagnostic triplet dt_010.

3. **Reasonable discharge range**: Mean discharge roughly matches expected value from drainage area and precipitation.
   - Quick check: Q_mean (m3/s) ~ (P_annual_mm * Area_km2 * Runoff_coeff) / (365.25 * 86400 / 1000)
   - If order of magnitude wrong: Likely a unit error upstream.

4. **No constant zero discharge**: If flo_out is always zero, the routing or connectivity is broken.
   - Check channel connectivity in chandeg.con

5. **Nutrient loads physically reasonable**: Total N export typically 1-50 kg/ha/yr for agricultural basins.
   - If >100 kg/ha/yr: Likely fertilizer input too high or sediment transport overestimated.

## Common Pitfalls

> **PITFALL**: Wrong outlet channel ID
> Parsing channel_sd for the wrong channel ID gives discharge for an internal reach, not the outlet. Values are lower than expected and performance metrics are poor.
> **Do this instead**: Identify the outlet channel from the connectivity files. It is usually the channel with no downstream connection, or the channel with the highest accumulation.

> **PITFALL**: Including warmup period in performance evaluation
> The first 2-3 years have arbitrary initial conditions. Including them in NSE calculation degrades the metric even if calibration is good.
> **Do this instead**: Exclude nyskip years from all performance calculations.

> **PITFALL**: Nutrient mass balance not closing (error >10%)
> Indicates a nutrient source or sink is not accounted for. Common cause: atmospheric deposition not enabled, or point sources not included.
> **Do this instead**: Check atmo.cli for atmospheric deposition; verify all point sources in recall.rec.
> See diagnostic triplet dt_015.

> **PITFALL**: Comparing daily simulated vs monthly observed
> If observed data is monthly, aggregate simulated daily to monthly before computing metrics. Comparing daily vs monthly gives meaningless results.
> **Do this instead**: Always match temporal resolution before computing metrics.

---

*This skill document is part of the SWAT+ knowledge infrastructure.*
*Stage 9 of 9 | Tools used: parse_channel_output, parse_basin_output, compute_performance_metrics, check_mass_balance | Related triplets: dt_010, dt_015*
