# S1: Climate Data Preparation

## Purpose

Convert global or station climate data into the exact format and units required
by HydroCNHS. This is the most error-prone step in the pipeline — wrong units
cause silent failures where the model runs without errors but produces
physically meaningless discharge.

## Inputs

| Input | Format | Unit | Source |
|-------|--------|------|--------|
| Daily temperature | CSV or NetCDF | varies (°C, K, °F) | ERA5, CMIP6, station |
| Daily precipitation | CSV or NetCDF | varies (mm, cm, m, kg/m²/s) | ERA5, CMIP6, station |
| Daily PET (optional) | CSV or NetCDF | varies (mm, cm) | Calculated or station |
| Outlet names | list | — | From basin delineation (S0) |
| Date range | string | YYYY/M/D | User-defined |

## Outputs

| Output | Format | Unit | Destination |
|--------|--------|------|-------------|
| temp dict | Python dict | °C | model.run(temp=...) |
| prec dict | Python dict | cm/day | model.run(prec=...) |
| pet dict (optional) | Python dict | cm/day | model.run(pet=...) |

Each dict maps `{outlet_name: [list_of_daily_values]}`.

## Procedure

1. **Identify source units** — Check metadata or headers for the unit of each variable.
   ERA5 uses K for temperature and m/day for precipitation. CMIP6 uses K and
   kg/m²/s. Most station data uses °C and mm/day.

2. **Extract spatial averages** — For each subbasin/outlet, extract the
   area-weighted average from gridded data, or assign the nearest station.

3. **Convert temperature**:
   - K → °C: subtract 273.15
   - °F → °C: (F - 32) × 5/9
   - Already °C: no conversion needed

4. **Convert precipitation** (CRITICAL):
   - mm/day → cm/day: **divide by 10**
   - m/day → cm/day: multiply by 100
   - kg/m²/s → cm/day: multiply by 86400, then divide by 10
   - Already cm/day: no conversion needed

5. **Convert PET** (if provided):
   - Same conversion as precipitation (usually mm/day → cm/day)
   - If not provided, HydroCNHS will auto-calculate using Hamon method

6. **Verify date alignment** — Ensure the number of values matches
   `(end_date - start_date).days + 1`. Missing days cause index errors.

7. **Run validation checks**:
   - Mean temperature should be in range [-20, 35] °C for most basins
   - Mean precipitation should be in range [0.01, 3] cm/day
   - No negative precipitation values
   - PET should be 0–1.5 cm/day for most basins

## Verification

After conversion, run these sanity checks:

```python
import numpy as np

for outlet in temp:
    t = np.array(temp[outlet])
    p = np.array(prec[outlet])
    print(f"{outlet}: temp mean={t.mean():.1f}°C, prec mean={p.mean():.3f} cm/day")

    assert t.mean() < 100, "Temperature likely in Kelvin!"
    assert p.mean() < 5, "Precipitation likely in mm/day, not cm/day!"
    assert not np.any(p < 0), "Negative precipitation!"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dt_001: Precipitation in mm not cm | Discharge 10× too high | Divide by 10 |
| dt_002: Precipitation in kg/m²/s | Discharge wildly wrong | ×86400 ÷10 |
| dt_003: Temperature in Kelvin | PET calculation wrong, muted seasonality | Subtract 273.15 |
| dt_004: PET in mm not cm | Evaporation 10× too high, discharge too low | Divide by 10 |

## Example

```python
# ERA5 data (temp in K, prec in m/day)
import numpy as np

# Convert
temp_C = era5_temp - 273.15        # K → °C
prec_cm = era5_prec * 100          # m/day → cm/day

# Build dicts
temp = {"WSLO": temp_C.tolist(), "DLLO": temp_C_dllo.tolist()}
prec = {"WSLO": prec_cm.tolist(), "DLLO": prec_cm_dllo.tolist()}

# Verify
for o in temp:
    assert np.mean(temp[o]) < 100, f"{o}: temp still in Kelvin!"
    assert np.mean(prec[o]) < 5, f"{o}: prec likely not in cm/day!"
```
