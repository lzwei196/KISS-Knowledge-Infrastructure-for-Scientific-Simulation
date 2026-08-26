# Stage 1: Forcing Preparation

## Purpose

Convert gridded forcing data (CMFD or MSWX) into TOPMODEL's `inputs.dat` format.
This is the most error-prone stage due to critical unit conversions.

## Inputs

| Input | Unit | Source |
|-------|------|--------|
| Precipitation | mm/day (CMFD) or mm/3hr (MSWX) | NetCDF files |
| Temperature | K | NetCDF files |
| Shortwave radiation | W/m² | NetCDF files |
| Wind speed | m/s | NetCDF files (for Penman-Monteith) |
| Pressure | Pa | NetCDF files (for Penman-Monteith) |
| Specific humidity | kg/kg | NetCDF files (for Penman-Monteith) |
| Basin shapefile | — | From Stage 0 |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| inputs.dat | TOPMODEL text | nstep, dt, then rain/pe/qobs per timestep |

## Procedure

1. **Extract basin-average forcing**:
   - Load NetCDF files for each variable and year
   - Clip to basin boundary (shapefile mask) or use nearest grid cell
   - Compute spatial mean for each time step

2. **Compute Potential Evapotranspiration (PET)**:
   - TOPMODEL needs PE in m/hr — it does NOT compute PET internally
   - Use Hargreaves (simple): `PE = 0.0023 * (Tmean+17.8) * sqrt(Trange) * Ra`
   - Or Penman-Monteith (full): requires wind, pressure, humidity, radiation
   - Output: PE in mm/day

3. **CRITICAL UNIT CONVERSIONS**:

   | Variable | From | To | Conversion |
   |----------|------|-----|------------|
   | Precipitation | mm/day | **m/hr** | ÷ 24,000 |
   | PE | mm/day | **m/hr** | ÷ 24,000 |
   | Temperature | K | °C | − 273.15 (for PET calc only) |
   | Qobs | m³/s | **m/hr** | × 3600 / basin_area_m² |

4. **Temporal disaggregation** (if needed):
   - Daily → hourly: divide by 24 (uniform) or use diurnal pattern
   - 3-hourly → hourly: interpolate or divide by 3

5. **Write inputs.dat**:
   ```
   {nstep}  {dt_hours}
   {rain_m_hr}  {pe_m_hr}  {qobs_m_hr}
   ...
   ```

## Verification

- [ ] Rain values are O(1e-4 to 1e-3) m/hr for typical storms
- [ ] PE values are O(1e-5 to 1e-4) m/hr
- [ ] Qobs values match expected range (or are 0 if not available)
- [ ] No negative values for rain or PE
- [ ] nstep matches expected number of time steps
- [ ] Total precipitation makes physical sense (~700–1200 mm/yr for Bengbu)

## Traps

| Trap | Symptom | Diagnosis | Fix |
|------|---------|-----------|-----|
| Precip in mm/day not m/hr | Discharge 24,000× too high | Check `max(rain)` — if >0.01, likely mm/day | ÷ 24,000 |
| Precip in mm/hr not m/hr | Discharge 1,000× too high | Check `max(rain)` — if >0.001, likely mm/hr | ÷ 1,000 |
| PE not computed | No evapotranspiration, all rain becomes runoff | sumae ≈ 0 in water balance | Compute PET from forcing |
| PE in mm/day not m/hr | ET way too large, negative root zone deficit | deficit_root_zone goes wildly negative | ÷ 24,000 |
| Temperature still in K | PET hugely overestimated | Hargreaves: (290+17.8) instead of (17+17.8) | − 273.15 |
| Missing data (NaN) | Model crashes or produces garbage | Check for NaN in inputs.dat | Fill with 0 (rain) or interpolate |

## Example

```bash
python tools/convert_forcing_to_topmodel.py \
  --forcing-dir KISSPATH_FORCING/huai/Data_forcing_01dy_025deg/ \
  --start-date 1980-01-01 --end-date 1990-12-31 \
  --lat 33.0 --lon 117.0 --dt-hours 24 \
  --output data/inputs.dat
```
