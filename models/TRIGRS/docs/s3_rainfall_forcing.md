# Stage 3: Rainfall Forcing Preparation

## Purpose

Convert rainfall data from meteorological sources into TRIGRS-format rainfall intensity grids and temporal parameters. This is the most error-prone stage due to unit conversions: TRIGRS expects rainfall intensity in **meters per second (m/s)**, while most data sources provide mm/hr, mm/day, or cumulative mm.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Rainfall data | CSV, NetCDF, gauge records | CMFD, MSWX, weather stations | Time series of rainfall |
| DEM grid | ESRI ASCII (.asc) | Stage 1 | For grid dimensions and extent |
| Event timing | Manual / automatic | Event analysis | Start/end times of storm |

## Outputs

| Output | Format | Unit | Description |
|--------|--------|------|-------------|
| ri1.asc, ri2.asc, ... | ESRI ASCII grid | **m/s** | Rainfall intensity per period |
| cri array | Values for tr_in.txt | **m/s** | Intensity values per period |
| capt array | Values for tr_in.txt | **seconds** | Cumulative time boundaries |

## Procedure

1. **Identify rainfall event**
   - Select storm event for analysis
   - Define start and end times
   - Determine number of distinct intensity periods

2. **Convert rainfall to intensity in m/s**

   **CRITICAL CONVERSION TABLE:**

   | Source unit | To m/s | Formula | Example (20 mm/hr) |
   |------------|--------|---------|---------------------|
   | mm/hr | divide by 3,600,000 | I(m/s) = I(mm/hr) / 3.6e6 | 5.56e-6 m/s |
   | mm/day | divide by 86,400,000 | I(m/s) = I(mm/day) / 8.64e7 | 2.31e-7 m/s |
   | mm/3hr | divide by 10,800,000 | I(m/s) = I(mm/3hr) / 1.08e7 | -- |
   | in/hr | multiply by 7.056e-6 | I(m/s) = I(in/hr) * 7.056e-6 | -- |
   | m/hr | divide by 3,600 | I(m/s) = I(m/hr) / 3600 | -- |

3. **Define rainfall periods**
   - TRIGRS uses constant-intensity periods (step functions)
   - Each period has one uniform intensity value
   - Periods are defined by cumulative time boundaries `capt()`
   - Total must equal simulation duration `t`

4. **Create rainfall grids**
   - One grid per period, matching DEM dimensions
   - Uniform rainfall: same value in all cells
   - Spatially variable: interpolate station/gridded data to cells

5. **Set initial infiltration rate (rizero)**
   - Background steady-state infiltration rate
   - Typically set to a small fraction of Ks
   - Can use a grid for spatial variation

6. **Convert all times to seconds**
   - Total duration `t`: in **seconds**
   - Period boundaries `capt()`: in **seconds**
   - Example: 48-hour storm -> t = 172800, capt = 0, 86400, 172800

## Verification

```bash
# Run the rainfall converter
python convert_rainfall_to_trigrs.py \
    --input rainfall.csv \
    --input_unit mm/hr \
    --dem dem.asc \
    --output_dir data/output/

# Verify converted values
python3 -c "
import numpy as np
ri = np.loadtxt('data/output/ri1.asc', skiprows=6)
valid = ri[ri != -9999]
print(f'Rainfall intensity: {valid[0]:.6e} m/s')
print(f'Equivalent: {valid[0] * 3.6e6:.2f} mm/hr')
assert valid[0] < 1e-3, 'Intensity > 1e-3 m/s is unrealistic!'
"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Rainfall in mm/hr used as m/s | Instant saturation, FS=0 everywhere | Divide by 3.6e6 |
| Time in hours instead of seconds | Wrong event duration/timing | Multiply by 3600 |
| capt() not starting at 0 | First period skipped | Ensure capt(1) = 0 |
| capt() not ending at t | Last period truncated or extended | Ensure capt(nper+1) = t |
| nper mismatch with cri/capt count | TRIGRS crash reading tr_in.txt | Verify: len(cri)=nper, len(capt)=nper+1 |
| rizero > Ks | Non-physical; more infiltration than conductivity allows | Set rizero < Ks |
| Cumulative rainfall used | Intensity massively wrong | Convert to rate (mm/hr) first |

## Example

```
# 48-hour storm with two periods:
# Period 1: 12 hours at 5 mm/hr
# Period 2: 36 hours at 20 mm/hr

# Convert to TRIGRS units:
# Period 1: 5 mm/hr / 3.6e6 = 1.389e-6 m/s, duration = 43200 s
# Period 2: 20 mm/hr / 3.6e6 = 5.556e-6 m/s, duration = 129600 s

# tr_in.txt entries:
nper = 2
t = 172800

cri(1), cri(2)
1.389e-6, 5.556e-6

capt(1), capt(2), capt(3)
0, 43200, 172800
```
