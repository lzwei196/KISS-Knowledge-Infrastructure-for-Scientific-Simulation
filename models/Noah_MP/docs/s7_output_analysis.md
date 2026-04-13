# Stage 7: Output Analysis

## Purpose

Extract, parse, and analyze Noah-MP LDASOUT output files to produce timeseries CSV,
summary statistics, and validation metrics. This stage converts raw NetCDF model output
into formats suitable for comparison with observations and downstream coupling.

## Inputs

| Input | Source | Format | Required |
|-------|--------|--------|----------|
| LDASOUT files | Stage s6 | NetCDF | Yes |
| Observation data | External | CSV/NetCDF | For validation only |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Timeseries CSV | CSV | Extracted variables at selected grid point |
| Statistics JSON | JSON | Summary statistics and derived metrics |
| Validation figure | PNG | Observed vs simulated comparison |

## Procedure

### 1. Extract timeseries

Use the output parser tool to extract key variables:

```bash
python ki/tools/parse_noahmp_output.py \
  --output_dir ./run/output/ \
  --variables TSK,SMOIS,TSLB,HFX,LH,GRDFLX,SFCRUNOFF,UDRUNOFF,SNOW,LAI \
  --output results.csv \
  --stats_json results_stats.json
```

### 2. Key output variables and interpretation

| Variable | Unit | Typical Range | Physical Meaning |
|----------|------|--------------|------------------|
| TSK | K | 250-320 | Surface skin temperature |
| SMOIS_L1 | m³/m³ | 0.05-0.45 | Top-layer soil moisture |
| SMOIS_L2-L4 | m³/m³ | 0.10-0.45 | Deeper soil moisture |
| TSLB_L1 | K | 260-310 | Top-layer soil temperature |
| HFX | W/m² | -50 to 300 | Sensible heat flux (+ = upward) |
| LH | W/m² | 0 to 500 | Latent heat flux (+ = upward) |
| GRDFLX | W/m² | -100 to 100 | Ground heat flux (+ = into soil) |
| SFCRUNOFF | m (accum) | 0-2 | Accumulated surface runoff |
| UDRUNOFF | m (accum) | 0-5 | Accumulated subsurface runoff |
| SNOW | mm | 0-2000 | Snow water equivalent |
| LAI | m²/m² | 0-8 | Leaf area index |

### 3. Compute derived quantities

**Evapotranspiration (ET)**:
```python
ET_mm_hr = LH / 2.5104e6 * 3600  # W/m² -> mm/hr (via latent heat of vaporization)
ET_mm_day = ET_mm_hr * 24
```

**Runoff (incremental)**:
```python
# SFCRUNOFF and UDRUNOFF are accumulated since simulation start
# Compute incremental per output step:
runoff_sfc_mm = diff(SFCRUNOFF) * 1000  # m -> mm
runoff_sub_mm = diff(UDRUNOFF) * 1000
total_runoff_mm = runoff_sfc_mm + runoff_sub_mm
```

**Baseflow index (BFI)**:
```python
BFI = sum(UDRUNOFF_inc) / sum(total_runoff)  # Should be 0.3-0.8 for most basins
```

**Bowen ratio**:
```python
Bowen = HFX / LH  # Typical: 0.1-0.5 (humid), 1-5 (arid)
```

### 4. Validation metrics

For hydrological validation against observed streamflow:

| Metric | Formula | Good Range |
|--------|---------|------------|
| NSE | 1 - Σ(Qobs-Qsim)²/Σ(Qobs-Qmean)² | > 0.5 |
| KGE | 1 - √((r-1)² + (β-1)² + (γ-1)²) | > 0.5 |
| PBIAS | 100 × Σ(Qsim-Qobs)/Σ(Qobs) | -15% to +15% |
| RMSE | √(Σ(Qobs-Qsim)²/N) | Depends on magnitude |
| R² | Pearson correlation squared | > 0.6 |

For soil moisture validation against SMAP/in-situ:

| Metric | Formula | Good Range |
|--------|---------|------------|
| ubRMSE | RMSE after bias removal | < 0.04 m³/m³ |
| R | Pearson correlation | > 0.6 |
| Bias | mean(sim) - mean(obs) | < 0.05 m³/m³ |

### 5. Energy balance check

```python
# Net radiation
Rn = SWDOWN - SWDOWN*ALBEDO + LWDOWN - EMISS*5.67e-8*TSK**4

# Balance residual (should be near zero)
residual = Rn - HFX - LH - GRDFLX
# Acceptable: |residual| < 5 W/m² on daily average
```

### 6. Common output issues

| Issue | Indicator | Likely Cause |
|-------|-----------|-------------|
| SMOIS constant | No temporal variability | Forcing precipitation is zero |
| TSK > 350 K | Unrealistic temperature | SW radiation too high or wrong units |
| HFX + LH >> Rn | Energy imbalance | Forcing units wrong |
| SFCRUNOFF = 0 always | No surface runoff | Sandy soil + low precipitation |
| SNOW accumulates forever | Never melts | Temperature forcing in Celsius (too cold) |
| LH < 0 always | Persistent condensation | Humidity forcing too high |

## Verification

- [ ] TSK annual range matches expected for latitude (e.g., 30-40K range at mid-latitudes)
- [ ] SMOIS responds to precipitation events
- [ ] Seasonal LAI cycle present (if dynamic_veg_option uses table LAI)
- [ ] Energy balance residual < 5 W/m² on daily average
- [ ] Total annual runoff is reasonable (200-1500 mm for most humid basins)
- [ ] Snow accumulates in winter, melts in spring (if applicable)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dt_017 | SFCRUNOFF always 0 | Accumulated variable — compute incremental difference |
| dt_018 | ET unrealistically high | LH in wrong units or humidity forcing error |
| dt_001 | Snow never melts | Temperature in Celsius causes perpetual sub-zero |

## Example

Parsing output and computing annual water balance:

```python
import pandas as pd

df = pd.read_csv("results.csv", parse_dates=["datetime"])

# Annual water balance
P_annual = forcing_precip_mm  # from forcing data
ET_annual = (df["LH"].mean() / 2.5104e6) * 86400 * 365 * 1000  # mm/yr
R_annual = (df["SFCRUNOFF"].iloc[-1] + df["UDRUNOFF"].iloc[-1]) * 1000  # mm/yr
dS = (df["SMOIS_L1"].iloc[-1] - df["SMOIS_L1"].iloc[0]) * 2000  # mm (approx)

print(f"P = {P_annual:.0f} mm/yr")
print(f"ET = {ET_annual:.0f} mm/yr")
print(f"R = {R_annual:.0f} mm/yr")
print(f"dS = {dS:.0f} mm/yr")
print(f"Balance: P - ET - R - dS = {P_annual - ET_annual - R_annual - dS:.0f} mm/yr")
```
