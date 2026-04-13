# Stage 5: Diagnostics and Verification

## Purpose

Analyze DART output to verify assimilation quality, diagnose problems,
and compute domain-appropriate performance metrics. Diagnostics use
both observation-space (obs_seq.final) and state-space (NetCDF)
output files.

## Inputs

| File | Format | Description |
|---|---|---|
| `obs_seq.final` | obs_seq | Observations with prior/posterior diagnostics |
| `preassim_mean.nc` | NetCDF | Prior ensemble mean |
| `analysis_mean.nc` | NetCDF | Posterior ensemble mean |
| `preassim_sd.nc` | NetCDF | Prior ensemble spread |
| `analysis_sd.nc` | NetCDF | Posterior ensemble spread |
| `obs_diag_output.nc` | NetCDF | Binned observation diagnostics |
| `input.nml` | Fortran namelist | obs_diag configuration |

## Outputs

| File | Format | Description |
|---|---|---|
| `obs_diag_output.nc` | NetCDF | Time-binned statistics |
| RMSE time series | CSV/plot | Root-mean-square error vs. time |
| Spread-skill | CSV/plot | Ensemble spread vs. RMSE |
| Rank histogram | CSV/plot | Ensemble calibration |
| Innovation statistics | CSV/plot | Obs minus prior statistics |

## Procedure

### Step 1: Run obs_diag

```bash
./obs_diag
```

Reads `obs_seq.final` and computes time-binned statistics:
- Bias (mean innovation)
- RMSE (root-mean-square error)
- Total spread (ensemble + observation)
- Observation count used/possible

Configure via `&obs_diag_nml` in `input.nml`:
```fortran
&obs_diag_nml
   obs_sequence_name  = 'obs_seq.final'
   obs_sequence_list  = ''
   first_bin_center   = YYYY, MM, DD, HH, 0, 0
   last_bin_center    = YYYY, MM, DD, HH, 0, 0
   bin_separation     = 0, 0, 0, 6, 0, 0
   bin_width          = 0, 0, 0, 6, 0, 0
   time_to_skip       = 0, 0, 0, 0, 0, 0
   trusted_obs        = 'null'
   Nregions           = 1
   lonlim1            = 0.0
   lonlim2            = 360.0
   latlim1            = -90.0
   latlim2            = 90.0
   reg_names          = 'Global'
/
```

### Step 2: Compute Key Metrics

#### RMSE (Root Mean Square Error)
```
RMSE = sqrt(mean((analysis - truth)^2))
```
For OSSEs, truth is known. For real data, compare to independent obs.

#### Ensemble Spread
```
Spread = sqrt(mean(ensemble_sd^2))
```
Should approximately equal RMSE for a well-calibrated ensemble.

#### Bias
```
Bias = mean(analysis - truth)
```
Should be close to zero. Systematic bias indicates model deficiency.

#### Rank Histogram
Plot the rank of the truth within the sorted ensemble. Should be
uniform (flat) for a well-calibrated ensemble. U-shaped = underdispersive
(too little spread). Dome-shaped = overdispersive.

### Step 3: MATLAB Diagnostics

```matlab
addpath('DART/diagnostics/matlab')
cd models/lorenz_63/work

% Total error over time
plot_total_err

% Phase space trajectory
plot_phase_space

% Ensemble error and spread
plot_ens_err_spread

% Rank histogram
plot_rank_histogram

% Observation diagnostics
plot_obs_netcdf
```

### Step 4: Python Diagnostics

```python
import netCDF4 as nc
import numpy as np

# Read analysis and truth
analysis = nc.Dataset('analysis_mean.nc')
truth = nc.Dataset('perfect_output.nc')

state_a = analysis.variables['state'][:]
state_t = truth.variables['state'][:]

# RMSE
rmse = np.sqrt(np.mean((state_a - state_t)**2))
print(f"RMSE: {rmse:.4f}")

# Spread
spread_ds = nc.Dataset('analysis_sd.nc')
spread = spread_ds.variables['state'][:]
mean_spread = np.sqrt(np.mean(spread**2))
print(f"Mean spread: {mean_spread:.4f}")
```

## Verification

1. **RMSE < prior RMSE**: Assimilation should reduce error.
   If not, check obs error, localization, inflation.

2. **Spread ≈ RMSE**: Ensemble is well-calibrated. If spread << RMSE,
   the ensemble is overconfident — increase inflation. If spread >> RMSE,
   the ensemble is underconfident — reduce inflation.

3. **Flat rank histogram**: Ensemble captures truth within its spread.

4. **Near-zero bias**: No systematic offset. Non-zero bias suggests
   model error or observation bias.

5. **Positive observation impact**: Assimilated obs reduce error.
   Use `obs_impact_tool` to quantify per-observation impact.

## Traps

1. **Evaluating only initial cycles**: The first few assimilation cycles
   may have large transients as the ensemble adjusts. Skip spinup
   (typically 10-50 cycles) before computing metrics.

2. **DART missing values in diagnostics**: Values of -888888.0 in
   NetCDF output mean "no data" — exclude from metric calculations.
   Using np.nanmean() won't help because -888888.0 is not NaN.

3. **Comparing wrong time slices**: DART output files may have multiple
   time steps. Ensure you're comparing corresponding times between
   analysis and truth.

4. **obs_diag time binning**: If bins don't align with observation
   times, observations may fall outside bins and be excluded from
   statistics. Set `bin_width` >= observation frequency.

5. **Spread computed from wrong variable**: Use `*_sd.nc` files for
   ensemble spread, NOT the standard deviation of `*_member_*.nc`.
   The SD files are computed with the proper N-1 normalization.

## Example

```bash
# Complete diagnostics for Lorenz 63
cd DART/models/lorenz_63/work

# Run obs_diag (after filter has completed)
./obs_diag

# Check output
ncdump -v rmse obs_diag_output.nc
ncdump -v bias obs_diag_output.nc
ncdump -v totalspread obs_diag_output.nc

# Python quick check
python3 -c "
import netCDF4 as nc
ds = nc.Dataset('obs_diag_output.nc')
print('Variables:', list(ds.variables.keys()))
print('RMSE:', ds.variables.get('rmse', 'not found'))
ds.close()
"
```
