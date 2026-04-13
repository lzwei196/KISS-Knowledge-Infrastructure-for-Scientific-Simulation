# Stage 4: Mass Balance Calibration

## Purpose

Calibrate OGGM's mass balance model against geodetic mass balance observations to ensure physically realistic glacier behavior. Without calibration, OGGM's default parameters produce reasonable but imprecise mass balance estimates — calibration typically reduces errors from ~500 mm w.e./yr to ~50 mm w.e./yr for individual glaciers. The calibration anchors the model to reality and is essential for credible projections.

The primary calibration dataset is Hugonnet et al. (2021), which provides geodetic mass balance rates for virtually every glacier on Earth for the period 2000-2020, derived from differencing DEMs from satellite altimetry. This is a transformative dataset — it means OGGM can be calibrated glacier-by-glacier, not just region-by-region.

## Prerequisites

- **Climate data processed** (Stage 3 complete — climate_historical.nc in each GDir)
- **Reference period overlapping geodetic MB** — The climate data must cover 2000-2020 (or a subset) for Hugonnet 2021 calibration
- **Hugonnet 2021 data** — Downloaded automatically by OGGM on first use (~100 MB)
- **Preprocessed GDirs** at L3+ (flowlines and catchments needed)

## Inputs

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| `working_dir` | directory | Yes | OGGM working directory |
| `ref_period` | string | No | '2000/01/01-2020/01/01' (default) |
| `inform_ref_mb` | bool | No | Use Hugonnet 2021 data (default true) |
| `tolerance_mm_yr` | float | No | Acceptable error tolerance (default 50 mm w.e./yr) |

## Procedure

### Step 1: Understand the Mass Balance Model

OGGM's mass balance model (MonthlyTIModel or derived classes) computes:

```
MB(z, month) = prcp_fac * prcp(month) * f_snow(z, month) - mu_star * max(T(z, month) - T_melt, 0)
```

Where:
- `prcp_fac` (pcf) — Precipitation correction factor (multiplicative)
- `prcp(month)` — Monthly precipitation from climate data
- `f_snow(z, month)` — Fraction of precipitation falling as snow at elevation z
- `mu_star` — Temperature sensitivity of melt (mm w.e. per degC per month)
- `T(z, month)` — Monthly temperature at elevation z (lapse-rate adjusted)
- `T_melt` — Melt threshold temperature (default 0 degC, but can be adjusted via tbias)
- `tbias` — Temperature bias added to T (degC)

The three calibration parameters:
1. **mu_star** (50-600 typical, can reach 0-1000): Controls melt rate. Higher = more melt per degree of warming. Heavily glaciated, continental regions tend to have lower mu_star.
2. **pcf** (0.5-5.0 typical): Precipitation correction. Higher = more snowfall = more accumulation. Mountain glaciers need pcf > 1 due to gauge undercatch.
3. **tbias** (-3 to +3 degC typical): Temperature offset. Compensates for systematic climate data biases.

### Step 2: Run Calibration

```python
from oggm import workflow, tasks

# Using Hugonnet 2021 geodetic MB (recommended)
workflow.execute_entity_task(
    tasks.mb_calibration_from_geodetic_mb, gdirs,
    informed_ref_mb=True,
    ref_period='2000/01/01-2020/01/01'
)
```

The calibration procedure:
1. Loads the Hugonnet 2021 geodetic MB for each glacier
2. Sets up the mass balance model with the glacier's climate data
3. Searches for (mu_star, pcf, tbias) that minimizes |MB_modeled - MB_observed| over the reference period
4. Uses a hierarchical approach: first optimize mu_star, then pcf, then tbias if needed
5. Stores calibrated parameters in `climate_info.pkl` within each GDir

### Step 3: Handle Calibration Failures

Not all glaciers calibrate successfully. Common failure modes:

**mu_star at bounds (dt_013):**
- mu_star = 0: Glacier gains mass even with no melt. Climate too cold or precipitation too high. Try reducing pcf or adding positive tbias.
- mu_star = 1000: Glacier loses mass even with maximum melt sensitivity. Climate too warm or precipitation too low. Try increasing pcf or adding negative tbias.

**No convergence (dt_011):**
- The optimization cannot find a parameter combination matching the observed MB. Often indicates: (a) wrong climate data (check dt_010), (b) surge-type glacier with non-climatic mass changes, (c) calving glacier where frontal ablation is significant.
- Solution: Exclude the glacier, or use regional mean parameters.

**No geodetic MB data (dt_012):**
- Some very small or newly delineated glaciers lack Hugonnet 2021 data. Use regional mean mass balance as the calibration target, or transfer parameters from nearby similar glaciers.

### Step 4: Validate Calibration

Run `validate_calibration.py` to assess quality:

```python
# For each glacier, compute:
error = MB_modeled - MB_observed  # mm w.e./yr
```

Key diagnostics:
- **Mean Absolute Error (MAE)**: Target < 50 mm w.e./yr across all glaciers
- **Bias**: Should be near zero — systematic positive bias means model overestimates mass loss
- **Fraction within tolerance**: Aim for > 90% of glaciers within +/- tolerance
- **Outlier list**: Glaciers with |error| > 3 * MAE — inspect individually
- **mu_star distribution**: Should be unimodal with a peak in 100-400 range
- **pcf distribution**: Most glaciers should have pcf in 1.0-3.0

### Step 5: Calibration Diagnostics Plot

Generate a diagnostic plot with four panels:
1. **mu_star histogram** — Distribution of calibrated mu_star values
2. **Error distribution** — Histogram of MB_modeled - MB_observed
3. **Modeled vs. observed scatter** — 1:1 line comparison
4. **Spatial map** — Color glaciers by calibration error

Glaciers with extreme parameters or high errors need individual attention.

## Expected Outputs

| Output | Location | Description |
|--------|----------|-------------|
| `climate_info.pkl` | Per GDir | Calibrated mu_star, pcf, tbias |
| Validation report | JSON | MAE, bias, fraction within tolerance |
| Diagnostics plot | PNG | 4-panel calibration quality visualization |

## Validation Checks

1. **mu_star not at bounds**: No glacier should have mu_star = 0 or mu_star = 1000
2. **pcf reasonable**: 0.5 <= pcf <= 5.0 for all glaciers
3. **tbias not extreme**: |tbias| < 5 degC for all glaciers
4. **MAE < tolerance**: Default tolerance is 50 mm w.e./yr
5. **Consistent spatial pattern**: Nearby glaciers should have similar parameters
6. **No NaN parameters**: All calibrated glaciers must have valid parameter values

## Common Pitfalls

### Wrong Reference Period
If the climate data doesn't fully cover the geodetic MB period (2000-2020), the calibration compares different time intervals. OGGM handles partial overlap but accuracy degrades. Ensure climate data covers at least 2000-2019 (W5E5 covers 1979-2019).

### Ignoring Surge-Type Glaciers
Surge-type glaciers have non-climatic mass redistributions (rapid advance/retreat cycles). Their geodetic MB includes dynamic mass transfer that the mass balance model cannot reproduce. Consider excluding surging glaciers (RGI surge flag = 2 or 3) or using them with caution.

### Over-Interpreting Individual Glacier Calibration
Geodetic MB has uncertainties of ~200-500 mm w.e./yr for individual glaciers. A "perfect" calibration matching the geodetic MB to <10 mm w.e./yr may be overfitting to a noisy observation. The calibration is most reliable when averaged over many glaciers.

### Custom Climate Recalibration
If using CMFD or MSWX instead of W5E5, the default calibration parameters are NOT valid. You must recalibrate. The same glacier with W5E5 and CMFD will have different mu_star values because the input climate differs.

### Equilibrium Assumption
The Hugonnet 2021 period (2000-2020) represents a period of mostly negative mass balance worldwide. Calibrating to this period means the model is tuned for retreat conditions. For LIA reconstructions or strong growth scenarios, parameter transferability is uncertain.

## Tools Reference

| Tool | Script | Purpose |
|------|--------|---------|
| `calibrate_mass_balance` | `tools/s4_calibration/calibrate_mass_balance.py` | Run MB calibration |
| `validate_calibration` | `tools/s4_calibration/validate_calibration.py` | Check calibration quality |
