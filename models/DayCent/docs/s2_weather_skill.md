# Stage S2 — Weather forcing

## Purpose
Build the daily `.wth` weather file consumed by DayCent. This is the most
common source of silent failures because of the **cm/day vs mm/day** unit
trap and the column ordering convention that has not changed since the 1990s.

## Inputs
- Latitude, longitude
- Year range (start_year, end_year)
- A daily forcing source: CMFD, MSWX, or NASA-POWER
  (auto-routed by `ki_tools_common.load_forcing.load_daily_forcing`)

## Outputs
- `<site>.wth` — whitespace-delimited file with 7 columns and one row per day.

## .wth column reference (NEVER misorder)
| Col | Variable | Unit | Type |
|-----|----------|------|------|
| 1 | day-of-month | 1..31 | int |
| 2 | month | 1..12 | int |
| 3 | year | 4-digit | int |
| 4 | day-of-year | 1..366 | int |
| 5 | Tmin | °C | float |
| 6 | Tmax | °C | float |
| 7 | precipitation | **cm/day** | float |
| 8 | (optional) solar radiation | langleys/day | float |
| 9 | (optional) relative humidity | % | float |

Optional columns 8/9 are only read when `usexdrvrs=1` in `sitepar.in`.

## Procedure
```bash
python tools/convert_forcing_to_daycent.py \
    --source cmfd --lat 40.78 --lon -81.93 \
    --year-start 1981 --year-end 2010 \
    --out wooster_run/wooster.wth
```

The converter:
1. Loads the daily series via `load_daily_forcing()` (CMFD/MSWX/NASA-POWER).
2. Converts Kelvin → °C if mean > 150 (CMFD raw is K, NASA-POWER is already °C).
3. Converts mm/day → cm/day if mean > 0.6 (most basins).
4. Writes the 7-column `.wth` file.
5. Calls `validate_outputs()` to assert annual precip is 5–500 cm/yr.

## Verification
- `head wooster.wth` shows 7 columns; column 7 looks like 0.04, 0.27 (cm/day),
  NOT 0.4, 2.7 (mm/day).
- Annual mean precip matches a published reference for the site
  (Wooster ≈ 95 cm/yr, central Nebraska ≈ 75 cm/yr, Beijing ≈ 60 cm/yr).
- `wc -l wooster.wth` = 365 × n_years (or 366 in leap years).
- Mean Tmin < mean Tmax; both are physically plausible.

## Traps
- **mm/day**: the #1 silent failure. CMFD, MSWX, NASA-POWER, ERA5, GLDAS all
  output mm/day. DayCent expects **cm/day**. The converter divides by 10.
- **Kelvin temperatures:** CMFD raw temperature is in K. The converter
  detects this from the magnitude and subtracts 273.15.
- **Leap-day handling:** if your forcing source skips Feb 29 (some daily
  GCMs), the column-4 day-of-year drifts. The converter trusts the date
  stamp from the forcing dict; verify with `awk '{print $3,$4}' | tail -2`.
- **Tmin > Tmax:** swap in CMFD `temp_min` vs `temp_max` keys. The
  validator catches this.
- **Decimal separator:** DayCent expects `.` as decimal separator. Locale
  set to `de_DE` may produce `,` and silently break parsing. Run scripts
  with `LC_ALL=C` for safety.

## Example output (Wooster, 1981 first 5 days)
```
  1   1 1981   1  0.57 -3.46 0.0000
  2   1 1981   2 -1.14 -6.92 0.2550
  3   1 1981   3 -4.93 -9.25 0.1370
  4   1 1981   4 -8.05 -23.81 0.0290
  5   1 1981   5 -15.19 -23.27 0.0000
```
