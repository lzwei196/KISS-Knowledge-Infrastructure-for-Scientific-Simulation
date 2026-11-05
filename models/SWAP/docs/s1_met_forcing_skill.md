# S1: Meteorological Forcing Conversion

## Purpose
Convert external meteorological data (CMFD, MSWX, or other sources) to the SWAP .met file format with correct units and structure.

## Inputs
- **Forcing source**: `cmfd`, `mswx`, `nasa_power` or `gswp3`, read through the shared loader
  `ki_tools_common.load_forcing.load_daily_forcing`. It returns DAILY values already in
  °C (`temp_min_c`, `temp_max_c`), mm/d (`precip_mm`), W/m² daily mean (`srad_wm2`),
  m/s (`wind_ms`), kg/kg (`shum_kgkg`) and Pa (`pres_pa`). It stops on any missing day
  inside `--start..--end` (never fills).
- **Site coordinates**: lat, lon for nearest grid point extraction

## Outputs
- SWAP .met file with columns: Station, DD, MM, YYYY, Rad, Tmin, Tmax, Hum, Wind, Rain, ETref, Wet

## Procedure
1. **Load daily forcing**: the shared loader picks the grid cell and gives daily values
   (no unit or time-step work left for this tool)
2. **Clip** to `--start..--end` (the loader checks only this window, via `period=`)
3. **Convert radiation**: W/m² daily mean → kJ/m²/d (multiply by 86.4 = 86400/1000)
4. **Temperature**: Tmin/Tmax already °C — written directly
5. **Convert humidity**: Specific humidity (kg/kg) + pressure (Pa) → vapor pressure (kPa):
   ```
   e_kPa = q * (P/1000) / (0.622 + 0.378 * q)
   ```
6. **Rainfall**: daily total mm/d → direct
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

### TRAP 3: Temperature in Kelvin (hand-made .met only)
If K not converted to °C: values around 293 → SWAP interprets as 293°C → crash or nonsense.
`convert_forcing_to_swap.py` gets °C from the shared loader.

### TRAP 4: Sub-daily rainfall not summed (hand-made .met only)
If 3-hourly values are written as daily records, the series is wrong. The shared loader returns
daily totals (`precip_mm`), so `convert_forcing_to_swap.py` writes them directly.

### TRAP 5: Wet column
`Wet` is the fraction of the day with rain. No forcing source gives it, so the tool writes 0.
SWAP reads it only with `SWRAIN = 2` and then stops on any rain day ("Rain and Wet donot
correspond"). Use `SWRAIN = 0` with the converter's single `.met` file. `SWRAIN = 1` or `3`
(and `SWMETDETAIL = 1`) make SWAP drop the `.met` extension and read yearly `<METFIL>.YYY`
files instead (pinned readswap.f90, "Extension .met in metfil discarded"); those yearly files
must be prepared separately, this converter does not write them.

## Example
```python
# What convert_forcing_to_swap.py does with the shared loader's daily output
d = load_daily_forcing("cmfd", lat, lon, y0, y1, forcing_dir=...,
                       variables=("P", "Tair", "SWd", "Wind", "spechum", "Pres"),
                       period=(start, end))
rad_kj = d["srad_wm2"] * 86400 / 1000                       # W/m² → kJ/m²/d
tmin_c, tmax_c = d["temp_min_c"], d["temp_max_c"]          # already °C
q, p = d["shum_kgkg"], d["pres_pa"]
e_kpa = q * (p / 1000) / (0.622 + 0.378 * q)                # kg/kg, Pa → kPa
rain_mm = d["precip_mm"]                                    # daily total
```
