# S2: Meteorological Forcing Preparation

## Purpose

Convert global or regional meteorological data into DHSVM's ASCII forcing format.
Each grid cell gets its own file with timestep records of temperature, humidity,
wind, radiation, and precipitation. This is the most error-prone stage due to
unit conversion traps.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Temperature | NetCDF/CSV | K or C | ERA5, CMFD, MSWX, Livneh |
| Relative Humidity | NetCDF/CSV | fraction or % | ERA5, CMFD |
| Wind Speed | NetCDF/CSV | m/s | ERA5, CMFD |
| Shortwave Radiation | NetCDF/CSV | W/m2 or MJ/m2/day | ERA5, CMFD |
| Longwave Radiation | NetCDF/CSV | W/m2 | ERA5, CMFD |
| Precipitation | NetCDF/CSV | mm/hr, mm/day, or m/s | ERA5, CMFD, PRISM |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `data_<lat>_<lon>` | ASCII, tab-separated | One file per grid cell |

**File content per line:**
```
MM/DD/YYYY-HH  Tair(C)  Wind(m/s)  RH(%)  Swin(W/m2)  Lwin(W/m2)  Precip(m/step)
```

## Procedure

1. **Identify source units** for each variable. This is the most critical step.
   Verify by checking the range of values in the source data:
   - Temperature: 250-310 → Kelvin; -40 to 40 → Celsius
   - RH: 0-1 → fraction; 0-100 → percent
   - Precip: >1 for hourly values → likely mm; <0.01 → likely m

2. **Apply unit conversions** using the conversion table:

   | Variable | Source → DHSVM | Formula |
   |----------|----------------|---------|
   | Temperature | K → C | `T_C = T_K - 273.15` |
   | Relative Humidity | frac → % | `RH_pct = RH_frac * 100` |
   | Wind Speed | km/hr → m/s | `W_ms = W_kmhr / 3.6` |
   | Shortwave | MJ/m2/day → W/m2 | `SW = MJ * 1e6 / 86400` |
   | Precipitation | mm/hr → m/step | `P_m = P_mm * dt_hr / 1000` |

3. **Temporal aggregation/disaggregation**: Match source timestep to DHSVM timestep.
   For 3-hourly DHSVM from hourly data: sum precipitation, average others.
   For 3-hourly from daily: distribute evenly (precipitation) or interpolate.

4. **Spatial mapping**: Create one file per DHSVM grid cell. The filename must
   contain the latitude and longitude with exactly `GRID_DECIMAL` decimal places.

5. **Write ASCII files** with DHSVM's date format: `MM/DD/YYYY-HH`.

6. **Run the converter tool:**
   ```bash
   python tools/convert_forcing.py \
     --input-dir /data/cmfd/ --output-dir forcing/ \
     --source-format cmfd --timestep 3 --grid-decimal 5 \
     --start-date 1970-10-01 --end-date 1971-10-01
   ```

## Verification

- **Temperature range**: All values should be -60 to +60 C. Values near 270+
  indicate Kelvin was not converted.
- **RH range**: All values 0-100. Values all <1 indicate fraction not converted.
- **Precipitation range**: Values should be <0.05 m/step for most timesteps.
  Values >1 indicate mm was not converted to m.
- **Shortwave radiation**: Should be 0 at night, peak ~800-1200 W/m2 at noon.
- **File naming**: Verify decimal places match `GRID_DECIMAL` in config.
- **Record count**: Each file should have `(end-start) / timestep` records.

## Traps

| Trap | Symptom | Severity | Fix |
|------|---------|----------|-----|
| Precip in mm instead of m | Massive floods, SWE explodes | Silent | Divide by 1000 |
| Temp in K instead of C | No snow anywhere, extreme ET | Silent | Subtract 273.15 |
| RH as fraction not percent | Near-zero humidity, extreme VPD | Silent | Multiply by 100 |
| Wrong GRID_DECIMAL | "Unable to open met file" fatal error | Fatal | Match decimal count |
| Timestamp format wrong | Dates parsed incorrectly, wrong data read | Silent | Use MM/DD/YYYY-HH |
| Missing grid cells | Zero forcing for uncovered cells | Degraded | Interpolate spatially |

## Example

```python
# Quick sanity check on converted forcing
import numpy as np
data = np.loadtxt("forcing/data_47.21875_-120.21875", dtype=str)
vals = data[:, 1:].astype(float)
print(f"Tair range: {vals[:,0].min():.1f} to {vals[:,0].max():.1f} C")
print(f"Wind range: {vals[:,1].min():.1f} to {vals[:,1].max():.1f} m/s")
print(f"RH range:   {vals[:,2].min():.1f} to {vals[:,2].max():.1f} %")
print(f"Precip max: {vals[:,5].max():.6f} m/step")
# Expected: Tair -40..40, Wind 0..30, RH 0..100, Precip < 0.05
```
