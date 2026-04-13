# S9: Output Analysis and Validation

## Purpose
Extract, visualize, and validate COAWST/ROMS output by comparing simulated fields against observations. Compute standard ocean model skill metrics to assess simulation quality.

## Inputs
| Input                  | Format     | Source               | Notes                            |
|------------------------|------------|----------------------|----------------------------------|
| History/avg files      | NetCDF     | Stage s8 output      | 3D + 2D fields with time dim    |
| Station files          | NetCDF     | Stage s8 output      | Time series at selected points   |
| Observation data       | CSV/NetCDF | Tide gauges, buoys   | Must overlap simulation period   |
| ROMS grid file         | NetCDF     | Stage s1             | For coordinate mapping           |

## Outputs
| Output              | Format  | Contents                                         |
|---------------------|---------|--------------------------------------------------|
| Time series CSV     | CSV     | Extracted variable time series at points          |
| Metrics JSON        | JSON    | RMSE, MAE, bias, correlation, NSE, skill         |
| Comparison plots    | PNG     | Observed vs simulated with metrics annotation     |

## Procedure

1. **Extract time series at observation points**:
   ```bash
   python3 ki/tools/parse_output.py \
     --history sandy_his.nc \
     --variable zeta --level surface \
     --lon -74.009 --lat 40.467 \
     --output battery_wl.csv
   ```

2. **Compare to observations**:
   ```bash
   python3 ki/tools/parse_output.py \
     --history sandy_his.nc \
     --variable temp --level surface \
     --lon -73.0 --lat 40.0 \
     --observations buoy_sst.csv \
     --output sst_comparison.csv --metrics
   ```

3. **Compute domain averages**:
   ```bash
   python3 ki/tools/parse_output.py \
     --history sandy_his.nc \
     --variable zeta --level surface \
     --domain-average \
     --output domain_ssh.csv
   ```

4. **Generate validation figures** (using matplotlib):
   ```python
   import matplotlib.pyplot as plt
   import pandas as pd

   df = pd.read_csv("sst_comparison.csv")
   fig, ax = plt.subplots(figsize=(12, 4))
   ax.plot(df["time"], df["observed"], "k-", label="Observed", linewidth=1.5)
   ax.plot(df["time"], df["temp"], "-", color="#2563EB", label="COAWST", linewidth=1.0)
   ax.legend()
   ax.set_ylabel("SST (°C)")
   plt.savefig("sst_validation.png", dpi=150)
   ```

## Verification

### Standard Metrics for Ocean Models
| Metric       | Formula                                            | Good Value      |
|-------------|-----------------------------------------------------|-----------------|
| RMSE        | √(mean((sim - obs)²))                               | < 10% of range  |
| MAE         | mean(|sim - obs|)                                    | < 10% of range  |
| Bias        | mean(sim - obs)                                      | Near 0          |
| Correlation | Pearson r                                            | > 0.8           |
| NSE         | 1 - Σ(sim-obs)² / Σ(obs-mean(obs))²                 | > 0.5           |
| Skill       | 1 - Σ(sim-obs)² / Σ(|sim-ō|+|obs-ō|)²              | > 0.7           |

### Expected Ranges by Variable
| Variable          | Typical RMSE       | Notes                              |
|-------------------|--------------------|------------------------------------|
| Sea level (zeta)  | 5–20 cm            | Tidal + storm surge                |
| SST               | 0.5–2.0 °C         | Depends on resolution              |
| Salinity          | 0.2–1.0 PSU        | Sensitive to river/precip forcing   |
| Currents (u, v)   | 5–20 cm/s          | Barotropic + baroclinic            |
| Wave height (Hsig)| 0.1–0.5 m          | Depends on offshore conditions     |

### Sanity Checks
- SST should be in range -2 to 35°C for most oceans
- Salinity should be 0–42 PSU (>45 indicates evaporation issue)
- Sea level should be ±2 m for tidal/storm surge (if > 5m, check units)
- Currents typically < 2 m/s (> 5 m/s suspicious unless in straits)

## Traps

**Comparing at wrong location.**
ROMS uses staggered grids. When extracting data for comparison, always use the **nearest rho-point** to the observation location. The parser tool does this automatically, but manual extraction must account for the stagger offset.

**Time zone mismatch.**
ROMS output time is typically in UTC. Observation data from tide gauges or buoys may be in local time. A 5-hour offset (UTC vs EST) will severely degrade metrics even if the simulation is perfect.

**Interpolation to depth.**
For 3D variables (temperature, salinity, currents), the S-coordinate vertical levels are terrain-following, not z-levels. Extracting "surface" means the top S-level, which is valid. But extracting at a specific depth (e.g., 10 m) requires interpolation through the S-coordinate, accounting for local bathymetry and SSH.

**Spin-up period.**
The first few days of simulation are affected by initial condition adjustment. Exclude the spin-up period (typically 3–7 days) from metric calculations.

## Example

Full validation workflow for Sandy sea level:
```bash
# Extract simulated water level at The Battery, NYC
python3 ki/tools/parse_output.py \
  --history Projects/Sandy/sandy_his.nc \
  --variable zeta --level surface \
  --lon -74.009 --lat 40.467 \
  --observations /data/obs/battery_wl_2012.csv \
  --output validation_battery.csv --metrics

# Result metrics (expected for well-calibrated Sandy run):
# RMSE: 0.15 m
# Correlation: 0.95
# NSE: 0.85
# Skill: 0.92
```
