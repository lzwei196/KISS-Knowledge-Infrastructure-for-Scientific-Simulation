# S1: Meteorological Forcing Conversion

## Purpose
Convert external meteorological data (CMFD, MSWX, or other sources) to the SWAP .met file format with correct units and structure.

## Inputs
- **CMFD forcing**: NetCDF files with prec (mm/day), temp (K), srad (W/m²), lrad (W/m²), wind (m/s), pres (Pa), shum (kg/kg)
- **MSWX forcing**: NetCDF with Tair (K), P (mm/3hr), SWd (W/m²), LWd (W/m²), wind (m/s), Pres (Pa), spechum (kg/kg)
- **Site coordinates**: lat, lon for nearest grid point extraction

## Outputs
- SWAP .met file with columns: Station, DD, MM, YYYY, Rad, Tmin, Tmax, Hum, Wind, Rain, ETref, Wet

## Procedure
1. **Extract grid point**: Find nearest lat/lon in forcing NetCDF
2. **Aggregate to daily**: MSWX is 3-hourly → daily aggregation needed
3. **Convert radiation**: W/m² → kJ/m²/d (multiply by 86.4 = 86400/1000)
4. **Convert temperature**: K → °C (subtract 273.15). For daily: extract Tmin and Tmax
5. **Convert humidity**: Specific humidity (kg/kg) + pressure (Pa) → vapor pressure (kPa):
   ```
   e_kPa = q * (P/1000) / (0.622 + 0.378 * q)
   ```
6. **Convert rainfall**: CMFD mm/day → direct. MSWX mm/3hr → sum 8 timesteps for mm/day
7. **Wind speed**: Direct (m/s). Ensure ALTW matches measurement height
8. **Set ETref**: Use -99.9 if not available (SWETR=0 will calculate from weather data)
9. **Write .met**: Header comments + CSV data rows
10. **Validate**: Check all ranges (Rad 0-50000, T -50..60, Hum 0-10 kPa, etc.)

## Verification
- `wc -l file.met` matches expected days + header lines
- `awk -F, '{print $5}' file.met | sort -n | tail -1` → max Rad < 50000 kJ/m²/d
- Hum values in 0.1-7 kPa range (NOT 0-1 range, NOT 0-100 range)
- No negative radiation or wind values
- Rain values in mm/d (0-500 reasonable, >500 suspect)

## Traps

### TRAP 1: Humidity units (CRITICAL — silent error)
SWAP expects **actual vapor pressure in kPa**, not relative humidity. If you pass:
- Relative humidity (0-1): ET will be massively overestimated (SWAP thinks air is bone-dry)
- Relative humidity (0-100): Values will be interpreted as >10 kPa → ET underestimated
- Specific humidity (kg/kg): Values near 0.01 → interpreted as 0.01 kPa → extreme drying

### TRAP 2: Radiation units (CRITICAL — silent error)
SWAP expects kJ/m²/d. Common mistakes:
- W/m² passed directly → values 0-400 interpreted as kJ/m²/d → 200× too low → no ET
- MJ/m²/d passed → values 0-30 → extremely low → minimal ET
- J/m²/d passed → values 0-4e7 → 1000× too high → extreme ET

### TRAP 3: Temperature in Kelvin
If K not converted to °C: values around 293 → SWAP interprets as 293°C → crash or nonsense

### TRAP 4: MSWX 3-hourly rainfall not aggregated
If 3-hourly values written as daily: rainfall 8× too low

## Example
```python
# CMFD → SWAP conversion
rad_kj = srad_wm2 * 86400 / 1000     # W/m² → kJ/m²/d
temp_c = temp_k - 273.15              # K → °C
e_kpa = shum * (pres/1000) / (0.622 + 0.378 * shum)  # kg/kg,Pa → kPa
rain_mm = prec_mm                     # CMFD already mm/day
```
