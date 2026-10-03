# s2_weather_prep — SHAW weather file (.wea)

**Standard path: build the weather DIRECTLY from the forcing source through the shared loader.**
This is the only weather tool; it reads no other model's forcing files. Do not read the source NetCDF files with your own code.

Tool: `tools/convert_forcing_to_shaw.py`

```bash
python convert_forcing_to_shaw.py --source nasa_power --lat 45.3 --lon -75.0 \
    --start_year 2015 --end_year 2019 --mode daily --output site.wea --summary_json site_weather.json
python convert_forcing_to_shaw.py --source cmfd --lat 32.43 --lon 115.6 \
    --forcing_dir KISSPATH_DATA/forcing/Data_forcing_03hr_010deg \
    --start_year 2010 --end_year 2010 --mode daily --output site.wea
```

| `--source` | What happens |
|---|---|
| `nasa_power`, `cmfd`, `mswx` | `ki_tools_common.load_forcing.load_daily_forcing` (daily) or `load_hourly_forcing` (hourly). The loader owns all source units. |
| `csv` / `--csv FILE` | Daily station table (date, tmax, tmin, precip, solar, wind, RH). Daily mode only. |

Which source: China -> `cmfd` (about 4 minutes per point-year). Elsewhere -> `nasa_power` for a single point.
`mswx` sits on an exfat disk: one reader at a time, and a point read takes hours.

What the tool does to the loader data:
- daily: dew point from specific humidity and pressure; solar stays a daily mean in W/m2; 2-digit year.
- hourly: RH from specific humidity, temperature and pressure; UTC -> local standard time (`--utc_offset`,
  default `round(lon/15)`); whole local days only; 3-hour sources become three hourly records per step
  (state held, rain split evenly); hours 0..23.
- It stops with a clear error when a needed variable is missing or NaN, when days are not consecutive,
  or when no source is named. It never fills in made-up values.

Checks after this step:
1. Read the printed annual rain totals and mean temperature. Near-zero rain means a unit error (triplet shaw_035).
2. `.inp` `MTSTEP` must match the mode: daily = 1, hourly = 0 (shaw_026).
3. The first weather day must be one day before `JSTART` (shaw_030).
4. Loader wind is the 10 m wind: set the `.sit` Line E instrument height (2nd value) to 10.0.

Old faults fixed on 2026-10-02: another model's forcing files read first (shaw_034; that reader is now removed), own CMFD reader with rain 10800 times
too small (shaw_035), hourly mode broken for gridded sources (shaw_036).
