# Stage 7: Output Analysis and Validation

## Purpose

Parse Delft3D NetCDF output files, extract key variables, compute validation
metrics against observations, and generate diagnostic plots. This stage
determines whether the simulation is scientifically useful.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| History file | _his.nc | Delft3D output | Time series at obs points |
| Map file | _map.nc | Delft3D output | Spatial fields at intervals |
| Observation data | CSV | Tide gauges / CMEMS | Ground truth for validation |
| Observation points | .xyn | Stage 5 config | Point coordinates + names |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Time series CSV | .csv | Extracted variables by station |
| Spatial CSV | _map.csv | Fields at specific timestep |
| Validation metrics | JSON / printed | RMSE, R², NSE, bias, skill score |
| Comparison plot | .png | Observed vs simulated with metrics |

## Procedure

### 1. Extract Time Series from History File

```bash
python ki/tools/parse_delft3d_output.py \
  --his_file output/model_his.nc \
  --output_csv results_timeseries.csv \
  --variables s1 ucx ucy \
  --stations "Station1" "Station2"
```

### 2. Extract Spatial Fields from Map File

```bash
python ki/tools/parse_delft3d_output.py \
  --map_file output/model_map.nc \
  --output_csv results_spatial.csv \
  --timestep -1  # last timestep
```

### 3. Compare with Observations

```bash
python ki/tools/parse_delft3d_output.py \
  --his_file output/model_his.nc \
  --obs_file observed_waterlevel.csv \
  --output_csv results.csv \
  --plot validation_plot.png
```

### 4. Manual Analysis with Python

```python
import netCDF4 as nc
import numpy as np

# Read history file
ds = nc.Dataset("output/model_his.nc")

# Get station names
stations = ds.variables["station_name"][:]
station_list = [b"".join(s).decode().strip() for s in stations]

# Get water level at all stations
s1 = ds.variables["s1"][:]  # (time, station)
times = nc.num2date(ds.variables["time"][:], ds.variables["time"].units)

for i, name in enumerate(station_list):
    wl = s1[:, i]
    print(f"{name}: mean={np.nanmean(wl):.3f} m, "
          f"range=[{np.nanmin(wl):.3f}, {np.nanmax(wl):.3f}]")

ds.close()
```

## Validation Metrics

| Metric | Formula | Good Value | Description |
|--------|---------|------------|-------------|
| RMSE | √(Σ(sim-obs)²/n) | < 0.15 m (WL) | Root mean square error |
| Bias | Σ(sim-obs)/n | < 0.05 m | Systematic offset |
| R² | 1 - SS_res/SS_tot | > 0.9 | Coefficient of determination |
| NSE | 1 - SS_res/SS_tot | > 0.7 | Nash-Sutcliffe Efficiency |
| PBIAS | 100·Σ(sim-obs)/Σ(obs) | < 10% | Percent bias |
| Willmott d | see formula | > 0.9 | Index of agreement |
| Skill Score | 1 - RMSE²/σ_obs² | > 0.8 | Normalized RMSE |

### Domain-Specific Targets

| Application | Variable | Acceptable RMSE | Good RMSE |
|-------------|----------|-----------------|-----------|
| Tidal simulation | Water level | < 0.20 m | < 0.10 m |
| Storm surge | Water level | < 0.30 m | < 0.15 m |
| Tidal currents | Velocity | < 0.20 m/s | < 0.10 m/s |
| Salinity | Salt conc. | < 3 PSU | < 1 PSU |
| Temperature | Water temp | < 2 °C | < 1 °C |

## Verification

1. **Phase alignment**: do tidal peaks in simulation match observed timing?
   A phase error of 30 minutes is acceptable for M2; > 1 hour indicates issues.

2. **Amplitude ratio**: simulated/observed tidal amplitude should be 0.8-1.2.
   Consistently low = too much friction. Consistently high = too little friction.

3. **Spring-neap pattern**: if simulation period includes spring and neap tides,
   verify that the modulation matches observations.

4. **Spatial patterns**: check map output for unrealistic gradients, dry cells
   that should be wet, or flow in wrong direction.

## Traps

1. **Time axis misalignment**: Delft3D output time is "seconds since RefDate",
   but observation data may use different time zones or references. Always verify
   that high tide in the simulation occurs at the same clock time as observations.

2. **Station mismatch**: station names in _his.nc must match the .xyn observation
   point file exactly. Trailing spaces, different capitalization, or truncation
   can cause wrong station to be extracted.

3. **Map file memory**: large _map.nc files (> 1 GB) can exhaust memory when loaded
   entirely. Use `timestep` parameter to extract single snapshots.

4. **Masked values**: NetCDF uses masked arrays for dry cells. Always use
   `.compressed()` or `.filled(np.nan)` before computing statistics.

5. **Metric sensitivity to mean**: NSE is sensitive to the overall mean. For
   variables with large mean and small variation (e.g., water depth in deep ocean),
   NSE can be artificially high even with poor skill.

## Example

```python
# Quick validation of tidal simulation
import netCDF4 as nc
import numpy as np

ds = nc.Dataset("output/model_his.nc")
s1 = ds.variables["s1"][:, 0]  # First station
times = nc.num2date(ds.variables["time"][:], ds.variables["time"].units)

# Tidal range
tidal_range = s1.max() - s1.min()
print(f"Simulated tidal range: {tidal_range:.2f} m")

# Check for M2 signal (~12.42 hours)
from numpy.fft import fft, fftfreq
dt_hr = (times[1] - times[0]).total_seconds() / 3600
n = len(s1)
freqs = fftfreq(n, d=dt_hr)
spectrum = np.abs(fft(s1 - s1.mean()))

# Find peak near M2 frequency (1/12.42 hr⁻¹)
m2_freq = 1.0 / 12.42
idx = np.argmin(np.abs(freqs[:n//2] - m2_freq))
print(f"M2 amplitude: {2*spectrum[idx]/n:.3f} m")

ds.close()
```
