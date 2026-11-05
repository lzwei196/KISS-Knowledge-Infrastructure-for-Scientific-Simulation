# Observation Data Preparation -- Skill Document

> **Stage ID**: s2_observation_data
> **Pipeline order**: 2 of 6
> **Depends on**: none for one point; s1 (the basin polygon) for a basin mean

## Purpose

Build the weather input of a CRHM run, the `.obs` file. It is the model's only
weather input. A wrong unit, a missing step or a wrong declaration line gives
either a crash with no message or a run that finishes with wrong numbers.

**Rule: build the `.obs` straight from the forcing source**, with `build_obs.py`.
It is the only weather tool of this KI, for every kind of run.

## How it works: two halves

1. **Source -> standard series** (shared loader, `ki_tools_common.load_forcing`).
   Every source gives the same series: time, `temp_c`, `precip_mm` (mm in the
   step), `srad_wm2`, `lrad_wm2`, `wind_ms`, `shum_kgkg`, `pres_pa`.
2. **Standard series -> `.obs`** (this KI, `tools/s2_observation_data/build_obs.py`).
   Turns specific humidity into relative humidity and writes the file CRHM reads.

Half 2 is the same for every source. A new dataset needs half 1 only.

## Prerequisites

- [ ] Source chosen and named: `cmfd`, `mswx`, `nasa_power`, or a `table` you made
- [ ] Place: one point (lat, lon) or the basin polygon
- [ ] Period: whole years, `--start_year` to `--end_year`
- [ ] Python environment: `KISSPATH_PYTHON_ENV/bin/python`

## Inputs

| Input | Description |
|-------|-------------|
| `--source` | `cmfd`, `mswx`, `nasa_power` or `table`. **No default: name it.** |
| `--lat --lon` | one point: the grid cell nearest to it |
| `--basin_shp` | basin polygon: mean over every grid cell inside it (`cmfd` only) |
| `--forcing_dir` | root folder of the `cmfd` / `mswx` store |
| `--start_year --end_year` | whole years; the series must cover them fully |
| `--precip_scale` | bias correction only (default 1.0); 10 or more is refused |
| `--table_path --table_name` | for `--source table` (a new dataset) |
| `--output_path` | the `.obs` file; `<name>.meta.json` is written next to it |

## Procedure

### Step 1: Choose the source and the place

| Source | Step | Period | Notes |
|--------|------|--------|-------|
| `cmfd` | 3 h | 1951-2024, China (15-55 N, 70-140 E) | default for China |
| `mswx` | 3 h | 1979 on, global | 1979, 2011 and the current year have faulty files and are refused |
| `nasa_power` | 1 h | 2001 on, global | network; coarse (about 0.5 deg) |
| `table` | yours | yours | a dataset with no reader yet, see Step 2c |

One point or a basin mean? CRHM takes ONE weather series and spreads it over the
HRUs by elevation (`obs_elev`, `lapse_rate`). One grid cell for a large basin is a
sample of one: for the Yarlung Tsangpo at Nuxia (205,000 km2) the centre cell had
550 mm in 1970, the mean of the 1,944 cells inside the basin 660 mm. Use
`--basin_shp` for a basin run, `--lat --lon` for a plot, a station or a basin
smaller than a cell or two.

### Step 2a: One point

```bash
python tools/s2_observation_data/build_obs.py \
  --source cmfd --lat <lat> --lon <lon> \
  --forcing_dir KISSPATH_DATA/forcing/Data_forcing_03hr_010deg \
  --start_year <start> --end_year <end> \
  --output_path outputs/<run>/crhm/basin.obs
```

### Step 2b: Basin mean

```bash
python tools/s2_observation_data/build_obs.py \
  --source cmfd --basin_shp <basin polygon .shp / .geojson> \
  --forcing_dir KISSPATH_DATA/forcing/Data_forcing_03hr_010deg \
  --start_year <start> --end_year <end> \
  --output_path outputs/<run>/crhm/basin.obs
```

About 1.2 minutes per year whatever the basin size (each store file is read once).
A basin that sticks out of the CMFD area is refused, not averaged over its inside
part.

### Step 2c: A dataset that has no reader (new dataset)

Do half 1 yourself, guided by the dataset's data KI (what the file holds, in
which units), and write a **standard table**: a CSV with exactly these columns.

| Column | Meaning and unit |
|--------|------------------|
| `time` | UTC, `2003-01-01T00:00:00`, evenly spaced, from Jan 1 00:00 of the first year to one step before Jan 1 after the last year |
| `temp_c` | air temperature, deg C |
| `precip_mm` | precipitation **in the step**, mm (not a rate, not a day total) |
| `srad_wm2` | incoming short-wave, W/m2 (a mean over the step, not J/m2) |
| `lrad_wm2` | incoming long-wave, W/m2 |
| `wind_ms` | wind speed, m/s |
| `shum_kgkg` | **specific** humidity, kg/kg |
| `pres_pa` | air pressure, Pa |

```bash
python tools/s2_observation_data/build_obs.py \
  --source table --table_path my_dataset.csv --table_name "<dataset, place>" \
  --start_year <start> --end_year <end> --forcing_elev_m <elevation of the series> \
  --output_path outputs/<run>/crhm/basin.obs
```

- Relative humidity or dew point instead of specific humidity: convert with
  pressure. `e = RH/100 * es(T)` (or `e = es(Tdew)`), then
  `q = 0.622 * e / (p - 0.378 * e)`, `e` and `p` in the same unit.
- A variable the dataset does not have (often long-wave): take it from a source
  that has it and say so in `--table_name`. Do not invent it.
- To see a correct table, write one from a known source: add
  `--save_table example.csv` to a Step 2a command.
- What the tool cannot see and you must get right: the time zone (UTC), the wind
  height, and that precipitation and radiation are per step and not accumulated.

### Step 3: Read the meta file and pass the elevation on

`basin.obs.meta.json` holds what was built: steps, period, precipitation per year,
temperature and humidity range, and `forcing_elev_m`, the elevation the series
stands for (cmfd: from the store's elevation field; basin mean: the mean over the
cells). **Give it to stage s4:**

```bash
python tools/s4_parameter_config/derive_parameters.py ... --forcing_source cmfd \
  --forcing_elev_m <forcing_elev_m from the meta file>
```

Check the yearly precipitation in the meta file against what is known for the
place before going on.

Keep the `.obs.meta.json` beside the observations: it also declares
`clock_utc_offset_hours: 0` for the direct-source and standard-table UTC contract.
The project writer uses it with HRU longitude to align `global Time_Offset`.
For an older UTC file without this field, pass `--obs_utc_offset 0` when creating
the project. See the s4 document for station clock time and explicit overrides.

### Step 4: Validate the observation file

```bash
python tools/s2_observation_data/validate_obs_file.py \
  --obs_path outputs/<run>/crhm/basin.obs
```

**Expected result**: JSON report with status "PASS", no errors.

## What the tool refuses (nothing is written)

| Refusal | Meaning |
|---------|---------|
| no `--source` | name the source; there is no default |
| `N of M values missing` | the source has a gap; nothing is filled with a constant |
| `range ... outside ...` | a unit is wrong upstream (kelvin, hPa, RH in the humidity column) |
| `time axis: ... steps are not ... s apart` | a missing or doubled step, with its place |
| `does not cover <years>` | the series is shorter or longer than the years asked for |
| `--precip_scale ... not a bias correction` | 24 was the old hand repair for NASA POWER; not needed (dt_v013) |
| `not fully inside the CMFD grid` | the basin sticks out of the store's area |

## The `.obs` file CRHM needs

```
CRHM forcing from cmfd at (29.59, 89.13) 1970-2013     <- exactly ONE description line
t 1 (C)
p 1 (mm)                                               <- precipitation IN THE STEP
rh 1 (%)
u 1 (m/s)
Qsi 1 (W/m^2)
Qli 1 (W/m^2)
############################################           <- must be there
1970 1 1 0 0 -17.20 0.000 24.2 1.07 0.00 160.00
```

| Variable | From the standard series | Silent if wrong? |
|----------|--------------------------|------------------|
| `t` | `temp_c`, unchanged | No |
| `p` | `precip_mm`, unchanged: mm in the step. **Not** mm/d. | **YES** |
| `rh` | from `shum_kgkg`, `pres_pa`, `temp_c`: `e = q p / (0.622 + 0.378 q)`, `RH = e / es(T) * 100` | **YES** -- dt_001 |
| `u` | `wind_ms`, unchanged | No |
| `Qsi`, `Qli` | `srad_wm2`, `lrad_wm2`, unchanged | No |

There is no air-pressure variable in a CRHM `.obs`. A line `p 1 (kPa)` is read as
precipitation.

## Validation Checks

1. **Declarations**: `head -8 basin.obs` shows the six lines above and the `####` line.
2. **No gaps**: `validate_obs_file.py` reports 0 gaps.
3. **Humidity is percent**: the meta file's `rh_pct_min_max` lies in 0-100 and the
   maximum is well above 1. A maximum near 0.02 means specific humidity was passed
   through.
4. **Precipitation per year** in the meta file is believable for the place.

## Common Pitfalls

> **PITFALL**: Specific humidity passed as relative humidity (SILENT ERROR)
> CRHM reads 0.001-0.02 as percent: bone-dry air, no sublimation, SWE grows for
> ever. `build_obs.py` does the conversion; never write the `rh` column yourself.
> See diagnostic triplet dt_001.

> **PITFALL**: One grid cell for a large basin
> Use `--basin_shp`. See Step 1.

> **PITFALL**: `--precip_scale 24`
> The NASA POWER hourly unit changed in 2026 and the loader now handles it. A scale
> of 24 would give 24 times too much rain; the tool refuses it. See dt_v013.

> **PITFALL**: Time zone
> The sources stamp their steps in UTC and the file is written in UTC. CRHM works
> out the sun's position from the clock time. Far from the Greenwich meridian the
> radiation is hours out of step with the model's sun (about 6 h at 90 E). Known
> and not corrected by the tool; daily and longer results are less affected than
> the daily cycle.

> **PITFALL**: Observation file path in .prj is relative to working directory
> CRHM resolves the path from the folder it is started in, not from the `.prj`.
> Use an absolute path (create_prj_file.py --obs_path with a full path).
> See diagnostic triplet dt_007.

---

*This skill document is part of the hydrocraft-crhm knowledge infrastructure.*
*Stage 2 of 6 | Tools used: build_obs, validate_obs_file | Related triplets: dt_001, dt_003, dt_007, dt_011, dt_018, dt_020, dt_v001, dt_v013, dt_v014*
