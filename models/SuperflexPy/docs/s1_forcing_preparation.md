# S1: Forcing Data Preparation

## Purpose

Prepare meteorological forcing time series (precipitation, potential evapotranspiration)
in the correct units and array format for SuperflexPy model input. This stage transforms
raw data from stations, reanalysis products, or gridded datasets into numpy arrays with
consistent units (mm/d).

## Inputs

| Input | Format | Source | Notes |
|-------|--------|--------|-------|
| Precipitation | CSV/DAT column | Station gauge, ERA5, CHIRPS | May be in mm/h, m/d, kg/m2/s |
| PET | CSV/DAT column | Calculated (Penman-Monteith, Hargreaves) or gridded | May be in mm/month, W/m2 |
| Observed streamflow | CSV/DAT column | Gauging station | For calibration/validation |
| Date columns | year, month, day | Same file or separate | For time indexing |

## Outputs

| Output | Format | Units | Description |
|--------|--------|-------|-------------|
| P array | numpy.ndarray | mm/d | Precipitation time series |
| PET array | numpy.ndarray | mm/d | Potential evapotranspiration |
| Q_obs array | numpy.ndarray | mm/d | Observed streamflow (optional) |

## Procedure

1. **Read raw data**: Load CSV/DAT file, handle header rows and separators
2. **Extract columns**: Identify P, PET, Q columns by index (0-based)
3. **Convert units**: Apply conversion factors to get mm/d
   - Precipitation: mm/h * 24, m/d * 1000, kg/m2/s * 86400
   - PET: mm/month / 30.44, W/m2 * 0.0353
   - Q: m3/s * 86400 / (area_km2 * 1e6) * 1000 (to mm/d)
4. **Quality check**: Flag negatives, NaN fraction, unrealistic magnitudes
5. **Export**: Save as JSON (with arrays as lists) or .npy files

```bash
python ki/tools/convert_forcing.py \
    --input data/forcing.csv \
    --header-lines 7 \
    --p-col 6 --pet-col 7 --q-col 8 \
    --p-unit mm/d --pet-unit mm/d \
    --output forcing.json
```

## Verification

- [ ] P array length matches PET array length
- [ ] Mean daily P is 1-15 mm/d for most catchments
- [ ] PET is 0-10 mm/d (typical range)
- [ ] No negative P or PET values
- [ ] NaN fraction < 5%
- [ ] Total annual P is physically plausible (300-3000 mm/yr)

## Traps

| Trap ID | Description | Impact |
|---------|-------------|--------|
| dt_001 | P in meters instead of mm | Flows 1000x too large |
| dt_002 | PET in mm/month treated as mm/d | ET 30x too high, model dries out |
| dt_003 | Timestep mismatch (hourly data, daily dt) | ODE integration wrong |

## Example

Using the built-in test data (Maimai catchment, New Zealand):

```python
import numpy as np
import pandas as pd

data = pd.read_csv('test/reference_results/01_FR/input.dat',
                    header=6, sep=r'\s+|,\s+|,', engine='python')
P = data.iloc[:, 6].values    # mm/d
PET = data.iloc[:, 7].values  # mm/d
Q_obs = data.iloc[:, 8].values  # mm/d

print(f"P: mean={P.mean():.2f}, max={P.max():.2f} mm/d")
print(f"PET: mean={PET.mean():.2f}, max={PET.max():.2f} mm/d")
print(f"N timesteps: {len(P)}")
```
