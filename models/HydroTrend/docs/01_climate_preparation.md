# Stage 1: Climate Data Preparation

## Purpose

Convert global reanalysis, station observations, or gridded climate products
into the monthly temperature and precipitation statistics required by HydroTrend
(lines 8–23 of HYDRO.IN).

## Inputs

| Source | Variables Needed | Typical Units |
|--------|-----------------|---------------|
| ERA5 | 2m temperature, total precipitation | K, m/day |
| CRU TS | tmp, pre | °C, mm/month |
| CMFD | air_temperature, precipitation | K, mm/3hr |
| Station data | daily T, daily P | °C, mm/day |

## Outputs

### Annual trend parameters (HYDRO.IN lines 8–9)
```
24.9 0.001 1.5     # T_start(°C) T_change(°C/yr) T_std(°C)
1.24 0.0002 0.05   # P_start(m/yr) P_change(m/yr²) P_std(m)
```

### Monthly climate table (HYDRO.IN lines 12–23)
```
Jan  24 1.98  5 2.22    # month T_mean(°C) T_std(°C) P_total(mm) P_std(mm)
Feb  17 1.56 10 1.90
...
Dec  16 1.63 10 3.86
```

## Procedure

1. **Extract basin-average time series**:
   - For gridded data, compute area-weighted mean over the basin polygon
   - For station data, use Thiessen polygons or inverse-distance weighting

2. **Compute monthly statistics**:
   - `T_mean[m]`: Multi-year mean of daily temperature for each month
   - `T_std[m]`: Standard deviation of daily temperature within each month
   - `P_total[m]`: Multi-year mean of monthly precipitation total in **mm**
   - `P_std[m]`: Inter-annual standard deviation of monthly precipitation

3. **Compute annual trend parameters**:
   - `T_start`: Mean annual temperature at simulation start
   - `T_change`: Linear trend in annual temperature (°C/yr)
   - `T_std`: Standard deviation of annual mean temperature
   - `P_start`: Mean annual precipitation in **m/yr** (not mm!)
   - `P_change`: Linear trend in annual precipitation (m/yr²)
   - `P_std`: Standard deviation of annual precipitation (m)

4. **Write to HYDRO.IN format** using `convert_climate_to_hydrotrend.py`

## Verification

- [ ] Monthly P values are in **mm** (typical range: 5–500 mm/month)
- [ ] Annual P (line 9) is in **m/yr** (typical range: 0.1–5.0 m/yr)
- [ ] Sum of monthly P (mm) / 1000 ≈ annual P (m/yr) from line 9
- [ ] Temperature values are physically plausible for the region
- [ ] T_std values are positive and typically 0.5–5.0 °C
- [ ] No sign errors in T_change (positive = warming trend)

## Traps

### CRITICAL: Monthly precipitation units (mm vs m)
HydroTrend expects monthly precipitation in **millimeters** on lines 12–23.
The model internally divides by 1000 to convert to meters. If you provide
values already in meters, the internal conversion makes them 1000× too small,
producing negligible runoff.

**Detection**: Annual discharge near zero; Qbar approaches baseflow only.

### CRITICAL: Annual precipitation units (m/yr)
Line 9 expects annual precipitation in **meters per year**. If you provide
mm/yr, values will be 1000× too large, causing extreme flooding.

**Detection**: Qbar many orders of magnitude above expected values.

### Lapse rate sign
The lapse rate (line 24) should be positive (e.g., 6.5 °C/km) for the
standard atmosphere where T decreases with altitude. HydroTrend computes:
`T_elevation = T_base - lapserate × elevation_difference`

### Temperature from reanalysis
ERA5 and CMFD provide temperature in Kelvin. Always subtract 273.15 before
computing statistics. Forgetting this produces T_mean ~ 290°C.

## Example

```bash
python convert_climate_to_hydrotrend.py \
    --input era5_daily_basin_avg.csv \
    --output monthly_climate.txt \
    --precip-units m/day \
    --temp-units K \
    --temp-col t2m \
    --precip-col tp \
    --date-col time
```
