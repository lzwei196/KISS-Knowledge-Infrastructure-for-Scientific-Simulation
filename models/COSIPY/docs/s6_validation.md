# Stage 6: Validation and Calibration

## Purpose

Validate COSIPY simulation results against observations (stake measurements, remote sensing, published data) and calibrate model parameters to improve agreement.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| COSIPY output | Stage 4 | netCDF |
| Stake measurements | Field campaigns | CSV (TIMESTAMP, stake_id, cumMB) |
| Snow depth observations | AWS / manual | CSV |
| Published MB data | WGMS / literature | Various |
| Remote sensing | MODIS albedo / ICESat-2 | Various |

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| Validation metrics | Console / CSV | RMSE, MAE, bias, r, NSE |
| Validation plots | PNG | Observed vs simulated |
| Calibrated parameters | TOML | Updated constants.toml |
| stake_statistics.csv | CSV | Per-stake RMSE (built-in) |
| stake_simulations.csv | CSV | Simulated MB at stake locations (built-in) |

## Procedure

### 1. Built-in stake evaluation

Enable in `config.toml`:
```toml
[STAKE_DATA]
stake_evaluation = true
stakes_loc_file = "./data/input/HEF/loc_stakes.csv"
stakes_data_file = "./data/input/HEF/data_stakes_hef.csv"
eval_method = "rmse"
obs_type = "mb"  # or "snowheight"
```

**Stake location file format** (`loc_stakes.csv`):
```
id	lat	lon
S1	46.789	10.765
S2	46.792	10.768
```

**Stake data file format** (`data_stakes_hef.csv`):
```
TIMESTAMP	S1	S2
2009-01-01	0.0	0.0
2009-02-01	-0.15	-0.20
2009-03-01	-0.30	-0.45
```
Note: Stake data must be **cumulative** changes in meters water equivalent (m w.e.).

### 2. Validation metrics

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| RMSE | sqrt(mean((sim-obs)^2)) | Lower = better; <0.5 m w.e. is good |
| MAE | mean(abs(sim-obs)) | Robust to outliers |
| Bias | mean(sim-obs) | Positive = overestimation |
| r | Pearson correlation | >0.8 is good for MB |
| NSE | 1 - sum((sim-obs)^2) / sum((obs-mean(obs))^2) | >0.5 is acceptable |

### 3. Common calibration parameters

| Parameter | Effect | Typical range |
|-----------|--------|---------------|
| `albedo_fresh_snow` | Controls accumulation/melt ratio | 0.75 - 0.90 |
| `albedo_firn` | Aged snow reflectance | 0.45 - 0.65 |
| `albedo_ice` | Bare ice reflectance | 0.2 - 0.4 |
| `albedo_mod_snow_aging` | Snow aging speed | 6 - 30 days |
| `center_snow_transfer_function` | Rain/snow threshold | 0 - 2 K |
| `mult_factor_RRR` | Precip undercatch correction | 1.0 - 2.0 |
| `roughness_fresh_snow` | Turbulent flux magnitude | 0.1 - 1.0 mm |
| `roughness_ice` | Ice surface roughness | 0.5 - 5.0 mm |
| `initial_snowheight_constant` | Starting condition | Site-specific |

### 4. Calibration strategy

1. **Spinup**: Run 1+ year with approximate parameters to reach quasi-steady state
2. **Sensitivity analysis**: Vary each parameter by +/-20% and check MB response
3. **Manual calibration order**:
   a. Fix precipitation (mult_factor_RRR) to match winter accumulation
   b. Adjust albedo parameters to match summer melt rate
   c. Fine-tune roughness for turbulent flux partitioning
   d. Check initial conditions match start-of-period observations
4. **Automated calibration**: Monte Carlo or GLUE sampling over parameter ranges

### 5. Physical consistency checks

- Total melt energy should be consistent with observed melt:
  `melt_m_we = ME_mean * dt * n_steps / (1000 * L_f)` where L_f = 3.34e5 J/kg
- Sublimation should be negative (mass loss) and typically 5-20% of total ablation
- Albedo should decay from ~0.85 to ~0.55 over weeks without new snow
- Surface temperature should never exceed 273.16 K

## Verification

```bash
# Compare output statistics with published data
python -c "
import xarray as xr
ds = xr.open_dataset('data/output/Zhadang_ERA5_20090101-20090110.nc')
if 'MB' in ds:
    import numpy as np
    mb_cum = float(ds.MB.sum()) * 1000  # to mm w.e.
    print(f'Cumulative MB: {mb_cum:.1f} mm w.e. over {len(ds.time)} hours')

    # Annualize
    hours = len(ds.time)
    annual_mb = mb_cum * 8760 / hours
    print(f'Annualized MB: {annual_mb:.0f} mm w.e./yr')
    print(f'  Typical for Tibet: -300 to -1500 mm w.e./yr')
ds.close()
"
```

## Traps

1. **Stake data must be cumulative**: If stake data represents period-to-period changes, not cumulative changes from the start, the comparison will be wrong. Uncomment the `cumsum` line in COSIPY.py if needed.

2. **obs_type must match data**: If stakes measure snow height, set `obs_type = "snowheight"`. If they measure mass balance, set `obs_type = "mb"`. Wrong setting compares apples to oranges.

3. **Spatial mismatch**: COSIPY uses a KD-tree to find the nearest grid cell to each stake. If the grid resolution is very coarse, multiple stakes may map to the same cell.

4. **Precipitation undercatch**: AWS gauges systematically undercount snowfall by 20-80%. The `mult_factor_RRR` parameter compensates, but the correct factor is site-specific.

5. **Overfitting to short periods**: Calibrating on a single year may not generalize. Use split-sample validation (calibrate on years 1-5, validate on years 6-10).

## Example

```python
# Quick validation against published Zhadang MB
# Published annual MB: approximately -500 to -1000 mm w.e./yr
# (Maussion et al. 2011, Mölg et al. 2012)

import xarray as xr
ds = xr.open_dataset('data/output/Zhadang_ERA5_20090101-20091231.nc')
annual_mb_mm = float(ds.MB.sum()) * 1000  # m w.e. -> mm w.e.
print(f'Simulated annual MB: {annual_mb_mm:.0f} mm w.e.')
print(f'Published range: -500 to -1000 mm w.e.')
if -1200 < annual_mb_mm < -300:
    print('REASONABLE')
else:
    print('CHECK PARAMETERS')
ds.close()
```
