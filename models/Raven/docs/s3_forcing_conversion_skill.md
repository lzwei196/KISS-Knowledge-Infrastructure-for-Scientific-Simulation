# s3: Forcing Conversion and Unit Handling

## Purpose

Build the Raven `.rvt` forcing file straight from a forcing source (CMFD, MSWX or NASA POWER) with correct units. **This is the single most critical stage in the entire Raven pipeline.** Raven explicitly states: "Raven ignores units and will not do units conversion." Every unit error produces a silent failure — the model runs fine with completely wrong results.

Raven's input is made from the data source by this KI's own tool. No other model's input files are used and no other model has to be run first.

## Prerequisites

- The forcing source: `cmfd` (China, 0.1 deg), `mswx` (global, 0.1 deg) or `nasa_power` (global, point API). The tool reads it only through `ki_tools_common.load_forcing`.
- Where to read it — exactly one of:
  - `--basin_shp <polygon>`: the basin polygon (the same file s1 uses). **The normal choice for a lumped basin run.**
  - `--points_csv <file>`: a CSV with header `lat,lon`.
  - `--lat --lon`: one point. Only for a basin that fits inside one or two source cells.
- Start and end year (whole years; the first years are the spin-up).
- Optional: the gauge discharge table for calibration/validation (`--obs_file`).

## Tool command

Basin mean (normal case):
```bash
python tools/s3_forcing/convert_forcing_to_rvt.py \
    --forcing_source cmfd \
    --forcing_dir KISSPATH_DATA/forcing/Data_forcing_03hr_010deg \
    --basin_shp <basin polygon .shp> \
    --output_dir <run dir> --basin_name <name> \
    --start_year <year> --end_year <year> --include_full_forcing \
    --obs_file <gauge table> --obs_subbasin_id 1 \
    --obs_start_date <YYYY-MM-DD> --obs_end_date <YYYY-MM-DD>
```

One point:
```bash
python tools/s3_forcing/convert_forcing_to_rvt.py \
    --forcing_source cmfd --lat 35.5 --lon 100.15 \
    --output_dir <run dir> --basin_name <name> --start_year <year> --end_year <year>
```

| Option | Meaning |
|--------|---------|
| `--forcing_source` | `cmfd`, `mswx` or `nasa_power`. Required, no default. |
| `--forcing_dir` | Root folder of the cmfd / mswx store. Not used by nasa_power. |
| `--basin_shp` | Mean over every source grid-cell centre inside the polygon, weighted by cos(latitude). The tool reports the number of cells. Refused when no cell centre is inside, or when the polygon is not fully on the source grid. |
| `--points_csv` | Plain mean over the listed `lat,lon` points. |
| `--lat --lon` | One point (nearest source cell). |
| `--gauge_elev` | Elevation (m) the series stands for; written as the gauge `:Elevation`. cmfd: taken from the store's own elevation field when not given. mswx / nasa_power: required (use the area-weighted mean HRU elevation of the `.rvh`). Never guessed: with orographic corrections on, a wrong value shifts every HRU's temperature. |
| `--include_full_forcing` | Also write wind, shortwave, pressure (needed by radiation-based PET). |
| `--obs_file` | Gauge table: text with a header, a date column (`dates`/`date`/`time`) and a discharge column in m3/s (`Q`/`discharge`/`flow`). Negative values (-99) are missing. Written as `<basin>_obs.rvt`, which the main `.rvt` redirects to. |
| `--obs_subbasin_id` | SubBasin ID of the gauge in the `.rvh` (default 1). |
| `--obs_start_date`, `--obs_end_date` | Window of the observation file. Start it after the spin-up. |

Outputs in `--output_dir`: `<basin>.rvt`, `<basin>_obs.rvt` (with `--obs_file`), `<basin>_forcing_summary.json` (source, number of points, period, mean annual precipitation, precipitation per year, gauge elevation).

## What the tool does

1. Finds the points: the one point, the CSV points, or the source cell centres inside the polygon.
2. Reads the daily series of every point through `ki_tools_common.load_forcing` — `load_daily_forcing` for one point, `load_daily_forcing_points` for many points in one shared pass per year. The loader does the source's own unit work (CMFD precipitation is a rate in kg m-2 s-1; MSWX is mm per 3 hours; NASA POWER is mm/day).
3. Averages the points day by day (cos(latitude) weights for a polygon). Daily Tmax of the basin is the mean of the cells' daily Tmax; the same for Tmin.
4. Converts to Raven units (table below).
5. Checks, **before anything is written**: every value finite, every variable inside its physical range, every day of the period present once and in order, mean annual precipitation between 10 and 5000 mm. Any failure stops the tool with a clear message and writes nothing. No value is filled in.
6. Writes the `.rvt`, the observation `.rvt` and the summary JSON together.

## CRITICAL: Unit Conversion Table

| Raven variable | Loader series (unit) | Raven expected unit | Conversion in the tool |
|----------|------------------|---------------------|---------------------|
| PRECIP | `precip_mm` (mm in the day) | **mm/d** | none |
| TEMP_MAX | `temp_max_c` (degC) | **degC** | none |
| TEMP_MIN | `temp_min_c` (degC) | **degC** | none |
| TEMP_AVE | computed | **degC** | (Tmax+Tmin)/2 |
| WIND_VEL | `wind_ms` (m/s) | **m/s** | none |
| SW_RADIA | `srad_wm2` (W/m2, daily mean) | **MJ/m2/d** | x 0.0864 |
| AIR_PRES | `pres_pa` (Pa) | **kPa** | / 1000 |

Raw store units, handled inside the shared loader (do not redo them): CMFD precipitation kg m-2 s-1, temperature K, pressure Pa; MSWX precipitation mm/3h, temperature degC.

## Validation Checks

After generating .rvt, read `<basin>_forcing_summary.json` and verify:

- [ ] `n_points` is what you expect for the basin (0.1 deg cells: about 1 per 100 km2 at mid latitudes)
- [ ] Mean annual precipitation: 200-3000 mm/yr (most basins), and close to what is known for the basin
- [ ] Temperature range: -40 to +50 degC (if 230-320, still in Kelvin!)
- [ ] Shortwave radiation: 0-40 MJ/m2/d (if 0-400, still in W/m2!)
- [ ] Air pressure: 60-110 kPa at low elevation, about 60 kPa at 4000 m (if 60000-110000, still in Pa!)
- [ ] `gauge_elev_m` is close to the mean HRU elevation of the `.rvh`
- [ ] `obs_rvt.n_valid` is not zero and the observation window starts after the spin-up

## Common Pitfalls

- **dt_001**: Precip not a daily total — 8x error. The loader returns the day total; do not sum again.
- **dt_002**: Temperature in Kelvin — PET calculations and snowmelt completely wrong.
- **dt_003**: Shortwave in W/m2 instead of MJ/m2/d — PET 10x too high.
- **dt_004**: Pressure in Pa instead of kPa — vapor pressure calculations break.
- **dt_005**: Timestep mismatch — .rvt says interval=1.0 but data is not daily.
- **dt_010**: PRECIP not in .rvt at all — Raven fills with zeros, no warning.
- **dt_rav_046 / dt_rav_047**: the old routes (other-model forcing files, hand-made NetCDF readers) are gone; the shared loader is the only reader.
- **dt_rav_048**: one point for a large basin is a sample of one — use `--basin_shp`.
- **dt_rav_049**: a guessed gauge elevation breaks the orographic corrections; an observation window with no valid value is refused.

## Run time

CMFD basin mean: about 100 s per year for any number of cells (each monthly file is read once). One CMFD point: about 3 minutes per year. MSWX: several minutes per variable and year. NASA POWER: one network call per point and year — use it for a few points only, and not for basins inside China (use cmfd).

## Minimum vs Full Forcing

| PET Method | Minimum Forcing | Full Forcing Recommended? |
|-----------|----------------|--------------------------|
| PET_OUDIN | PRECIP + TEMP_AVE | No — temperature-only |
| PET_HARGREAVES_1985 | PRECIP + TEMP_MIN + TEMP_MAX | No |
| PET_PENMAN_MONTEITH | PRECIP + TEMP + WIND + RH + SW + PRESS | Yes — needs all 7 |
| PET_PRIESTLEY_TAYLOR | PRECIP + TEMP + SW | Recommended |

When in doubt, provide at minimum: PRECIP, TEMP_MIN, TEMP_MAX, TEMP_AVE. Raven will generate all other variables internally using its 40+ forcing function generators.
