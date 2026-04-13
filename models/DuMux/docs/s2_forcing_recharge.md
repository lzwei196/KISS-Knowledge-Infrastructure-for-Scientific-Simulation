# Stage 2: Forcing and Recharge Conversion

## Purpose

Convert meteorological data or recharge estimates from global datasets into DuMux-compatible boundary condition values. For groundwater models, the primary forcing is **recharge** — the fraction of precipitation that percolates to the water table.

## Inputs

| Input | Format | Source | Unit |
|-------|--------|--------|------|
| Precipitation | CSV time series | CMFD, MSWX, ERA5, gauges | mm/day or mm/3hr |
| Evapotranspiration (optional) | CSV time series | Remote sensing, Penman-Monteith | mm/day |
| Recharge fraction | scalar | Calibration, lysimeter data | 0–1 [-] |
| River stage (optional) | CSV time series | Gauge data | m above datum |

## Outputs

| Output | Format | Consumed by | Unit |
|--------|--------|-------------|------|
| Recharge rate time series | CSV | DuMux Neumann BC | kg/(m²·s) |
| Pressure boundary (optional) | CSV | DuMux Dirichlet BC | Pa |
| DuMux .input snippet | text | params.input file | - |

## Procedure

### Step 1: Obtain precipitation data

Common sources:
- **CMFD**: China Meteorological Forcing Dataset, 0.1°, 3-hourly, mm/3hr
- **MSWX**: Multi-Source Weather, 0.1°, daily, mm/day
- **ERA5**: ECMWF reanalysis, 0.25°, hourly, m/timestep

### Step 2: Compute recharge rate

**Method A — Simple fraction**:
```
R [mm/day] = P [mm/day] × f_recharge
```
Where `f_recharge` = 0.05–0.30 depending on soil, vegetation, slope.

**Method B — P minus ET**:
```
R [mm/day] = max(0, P - ET) × f_percolation
```

### Step 3: Convert units to DuMux

**CRITICAL**: DuMux Neumann boundary conditions use mass flux in kg/(m²·s).

```
R_dumux [kg/(m²·s)] = R [mm/day] × ρ_water / (86400 × 1000)
                    = R [mm/day] × 1000 / (86400 × 1000)
                    = R [mm/day] / 86400
                    = R [mm/day] × 1.1574e-5
```

**CRITICAL**: DuMux sign convention for Neumann BC:
- **Positive** = outward flux (leaving domain)
- **Negative** = inward flux (entering domain)
- Recharge enters from the top → **negative** value

```python
recharge_dumux = -R_mm_day / 86400.0  # negative = inflow
```

### Step 4: For head/pressure boundaries

Convert hydraulic head to absolute pressure:
```
p [Pa] = p_atm + ρ × g × (h - z)
       = 101325 + 1000 × 9.81 × (head_m - elevation_m)
```

### Step 5: Generate time-varying BC

For transient simulations, DuMux reads BC values from the Problem class. Time-varying BCs require either:
1. Hardcoded lookup table in the Problem `source()` or `neumann()` function
2. Reading from an external file at each time step
3. Using the `TimeDependent` interface

## Verification

1. **Recharge magnitude**: Typical values: 0.01–5 mm/day (1e-7 to 6e-5 kg/(m²·s)).
   - Arid: < 0.5 mm/day
   - Temperate: 0.5–2 mm/day
   - Tropical: 2–5 mm/day
2. **Sign check**: Recharge must be NEGATIVE in DuMux Neumann BC convention.
3. **Unit check**: If max |recharge| > 1e-3 kg/(m²·s), values are likely still in mm/day.
4. **Annual total**: Sum recharge over year. Should be 10–500 mm/year for most climates.

## Traps

### TRAP: mm/day vs kg/(m²·s) — off by 86,400
If precipitation in mm/day is used directly as DuMux flux, recharge is 86,400× too high. The water table will rise unrealistically.

**Detection**: Check if mean recharge flux > 1e-3 kg/(m²·s).
**Fix**: Divide by 86,400 (and multiply by ρ/1000 if needed).

### TRAP: Neumann sign convention
Positive Neumann = outflow in DuMux. Using positive values for recharge turns it into extraction. The water table drops instead of rises.

**Detection**: Water table drops despite precipitation.
**Fix**: Negate recharge values.

### TRAP: mm/3hr vs mm/day
CMFD provides precipitation in mm per 3-hour interval, NOT mm/day. Using mm/3hr as mm/day understates recharge by 8×.

**Detection**: Compare annual precipitation sum with climate normals.
**Fix**: Multiply by 8 to convert mm/3hr to mm/day, or by 8/86400 for kg/(m²·s).

### TRAP: Pressure BC must be absolute
Using gauge pressure (p=0 at surface) instead of absolute pressure shifts the entire hydraulic head field by ~10.3 m (1 atm). This can invert flow directions.

**Detection**: Computed heads are ~10 m below expected values.
**Fix**: Add 101325 Pa to all pressure boundary values.

## Example

```python
# Convert CMFD precipitation to DuMux recharge
import numpy as np

precip_mm_3hr = np.loadtxt("cmfd_precip.csv")  # mm per 3 hours
precip_mm_day = precip_mm_3hr * 8.0             # 8 intervals per day
recharge_fraction = 0.15
recharge_mm_day = precip_mm_day * recharge_fraction
recharge_dumux = -recharge_mm_day / 86400.0     # kg/(m²·s), negative = inflow

print(f"Mean recharge: {np.mean(np.abs(recharge_dumux)):.2e} kg/(m²·s)")
print(f"Equivalent: {np.mean(recharge_mm_day):.2f} mm/day")
```

**Tool**: `tools/convert_forcing_to_dumux.py`
```bash
python tools/convert_forcing_to_dumux.py \
    --input precip_daily.csv \
    --output recharge_bc.csv \
    --recharge_fraction 0.15 \
    --precip_unit mm_per_day
```
