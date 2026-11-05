# Rainfall Forcing Preparation — Skill Document

> **Stage ID**: s3_rainfall_forcing
> **Pipeline order**: 3 of 7
> **Depends on**: none (can run in parallel with S1 and S2)

## Purpose

Rainfall is the primary driver of stormwater runoff in SWMM. This stage prepares rainfall time series from historical gauge data, a gridded forcing source (CMFD, MSWX, NASA POWER), or synthetic design storms, and configures rain gages that assign rainfall to subcatchments.

The rainfall forcing stage has the highest potential for SILENT ERRORS in the entire SWMM workflow. Two critical issues dominate:

1. **FORMAT mismatch** (INTENSITY vs VOLUME): If the rain gage FORMAT does not match how the data is encoded, runoff volumes are wrong by a factor proportional to the recording interval. There is NO error message.
2. **Unit mismatch**: If FLOW_UNITS=CMS but rainfall is in inches (or vice versa), SWMM applies the wrong depth-to-volume conversion. There is NO error message.

This stage must be completed with extreme attention to data conventions.

## Prerequisites

Before starting this stage, verify:

- [ ] Rainfall source data is available (gauge records, a gridded source: CMFD / MSWX / NASA POWER, or design storm parameters)
- [ ] Recording interval is known (5-min, 15-min, hourly, daily)
- [ ] Data convention is known: is each value an instantaneous rate (mm/hr) or accumulated depth (mm/interval)?
- [ ] FLOW_UNITS has been decided (CFS or CMS) — this determines whether rainfall is in inches or mm
- [ ] Simulation period is defined (start/end dates)
- [ ] Python environment has: pandas, numpy

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Rainfall data | file / store | Gauge CSV, gridded source (CMFD / MSWX / NASA POWER), or design parameters | Raw precipitation data |
| Data format | string | Data documentation | 'intensity' (rate, mm/hr) or 'volume' (depth per interval, mm) |
| Recording interval | number | Data documentation | Minutes between measurements |
| FLOW_UNITS | string | Model configuration | CFS (rain in inches) or CMS (rain in mm) |
| Forcing store | directory | `KISSPATH_DATA/forcing/Data_forcing_03hr_010deg` (CMFD 3-hourly), `KISSPATH_FORCING` (MSWX) | For `--source cmfd` / `mswx`; NASA POWER needs the network, no folder |
| Rain gage point(s) | lat,lon | Study area | Where the gridded source is read |

## Procedure

### Step 1: Determine Rainfall Data Source

Three main sources, in order of preference:

**Historical gauge data** (best for calibration/validation):
- Actual measurements from rain gauges at or near the study area
- Must verify recording interval and format convention
- May have gaps that need filling

**Gridded forcing source** (when there is no gauge; real rain for any place and period):
- CMFD (China, 0.1 deg, 3-hourly, on disk), MSWX (global, 0.1 deg, 3-hourly, on disk), NASA POWER (global, hourly, network)
- Read straight from the source through the shared loader `ki_tools_common.load_forcing.load_hourly_forcing`; never from another model's input files (dt_023)
- 3-hourly or hourly: fine for multi-day totals and continuity, coarse for a street-scale peak (a 0.1 deg cell mean over 3 hours is far below a gauge's 5-minute peak)
- Use the `build_rain_timeseries_from_source` tool

**Design storms** (best for drainage design):
- Synthetic hyetographs for specific return periods
- SCS Type II (most common in eastern US), Chicago storm, constant intensity
- No calibration possible — design only
- Use the `generate_design_storm` tool

### Step 2: Create Rainfall Time Series

#### From historical gauge data:

```bash
python tools/s3_rainfall_forcing/create_rain_timeseries.py \
  --rain_csv data/rainfall/gauge_001.csv \
  --value_col rainfall_mm \
  --format depth_mm \
  --timestep_min 60 \
  --series_name RainGage1 \
  --output outputs/swmm_run/rainfall/rain_gauge1.dat
```

`--format depth_mm` (mm per step) is turned into mm/hr, so the gage FORMAT is INTENSITY; `--format intensity_mm_hr` is written as it is.

The `.dat` the rain tools write (tab-separated; rows with no rain are left out, SWMM reads a missing row of a rain gage as no rain):
```
;;SWMM Rainfall Timeseries: RainGage1
RainGage1	01/15/2020	01:00:00	2.3000
RainGage1	01/15/2020	02:00:00	5.1000
RainGage1	01/15/2020	03:00:00	8.7000
```
These rows go into `[TIMESERIES]` of the `.inp` as they are.

Date format: MM/DD/YYYY. Time format: HH:MM:SS. Value in mm (CMS) or inches (CFS).

#### From a gridded source (CMFD / MSWX / NASA POWER):

```bash
python tools/s3_rainfall_forcing/build_rain_timeseries_from_source.py \
  --source cmfd \
  --points "32.05,118.80" \
  --start_date 2020-07-01 --end_date 2020-07-31 \
  --forcing_dir KISSPATH_DATA/forcing/Data_forcing_03hr_010deg \
  --rain_format intensity \
  --series_name CMFD_Rain \
  --output outputs/swmm_run/rainfall/cmfd_rain.dat
```

Options: `--source cmfd|mswx|nasa_power` (required, no default); `--points "lat,lon;lat,lon"` (one or more; `--method average` = mean of the points, `nearest` = the point nearest to their centre); `--start_date` / `--end_date` (both days included); `--forcing_dir` (cmfd / mswx store; not used by nasa_power); `--rain_format intensity|volume`; `--series_name`; `--output`.

What it does: calls `load_hourly_forcing` (which returns `precip_mm` = mm IN THE STEP: 3 hours for cmfd / mswx, 1 hour for nasa_power), then
- `--rain_format intensity`: value = `precip_mm / step hours` (mm/hr) -> gage `FORMAT INTENSITY`
- `--rain_format volume`: value = `precip_mm` (mm per step) -> gage `FORMAT VOLUME`

and prints the `[RAINGAGES]` line to use: `INTERVAL 3:00` for cmfd / mswx, `1:00` for nasa_power. The same facts are in `<output stem>.summary.json` (source, points, step, total mm, daily totals).

It writes nothing and stops with an error when a value is missing or not finite, the time axis is uneven, or the period is not fully in the store. Time stamps are UTC.

Checked (2026-10-02): CMFD at Nanjing (32.05, 118.80), July 2020: 329.6 mm in the `.dat` (both formats) = the loader's sum for the same days. One 3-hourly point is right for a city core inside one 0.1 deg cell; for a larger area give several points.

To run the whole-city model on this series: `tools/run_city_swmm.py --rain_dat ... --rain_interval 3:00 --rain_format intensity` (see SKILL.md, Data Preparation).

#### Design storm:

```bash
python tools/s3_rainfall_forcing/generate_design_storm.py \
  --type SCS_II \
  --depth_mm 100 \
  --duration_hr 24 \
  --timestep_min 5 \
  --output outputs/swmm_run/rainfall/design_storm_100yr.dat
```

### Step 3: Define Rain Gages

Rain gages in SWMM connect rainfall time series to subcatchments. Each rain gage specifies:

| Parameter | Description | Critical? |
|-----------|-------------|-----------|
| Name | Unique gage identifier | |
| Format | INTENSITY or VOLUME | **YES — SILENT ERROR if wrong** |
| Interval | Recording interval (HH:MM) | **YES — must match data** |
| SCF | Snow catch factor (usually 1.0) | |
| Source | TIMESERIES or FILE | |
| Data | Time series name or file path | |

**FORMAT rules**:
- If raw data values represent **depth accumulated over each interval** (e.g., 2.5 mm fell in this 5-minute period): FORMAT = **VOLUME**
- If raw data values represent **instantaneous rainfall rate** (e.g., 30 mm/hr at this moment): FORMAT = **INTENSITY**

**INTERVAL** must match the data timestep exactly:
- 5-minute data: `0:05`
- 15-minute data: `0:15`
- Hourly data: `1:00`
- 3-hourly CMFD / MSWX (from `build_rain_timeseries_from_source`): `3:00`

### Step 4: Assign Rain Gages to Subcatchments

Every subcatchment in `[SUBCATCHMENTS]` must reference a valid rain gage. Assignment methods:
- **Nearest gage**: Each subcatchment uses the closest rain gage
- **Single gage**: All subcatchments use the same gage (for small study areas)
- **Thiessen weights**: Not directly supported in SWMM — use area-weighted average time series

### Step 5: Validate Rainfall Input

```bash
python tools/s3_rainfall_forcing/validate_rainfall_input.py \
  --timeseries outputs/swmm_run/rainfall/rain_gauge1.dat \
  --max_intensity 300
```

Validation checks:
1. FORMAT matches data convention
2. All values >= 0
3. No gaps > 2x the recording interval
4. Units consistent with FLOW_UNITS
5. Time series covers the simulation period
6. Maximum intensity is physically plausible (< 200 mm/hr for most locations)

## Expected Outputs

| Output | Path Pattern | Description |
|--------|-------------|-------------|
| Time series files | `{output_dir}/rain_*.dat` | SWMM-formatted rainfall data |
| Gage mapping | `{output_dir}/gage_mapping.csv` | Subcatchment-to-gage assignments |
| Validation report | (stdout/JSON) | Data quality assessment |

## Validation Checks

1. **FORMAT-data consistency**: Manually inspect 2-3 heavy rainfall events. If FORMAT=INTENSITY and a 5-min value is 50, that means 50 mm/hr (plausible for heavy rain). If FORMAT=VOLUME and a 5-min value is 50, that means 50 mm in 5 minutes = 600 mm/hr (extreme, possibly wrong).
2. **Total depth sanity**: Sum the time series over the simulation period. Compare against known annual rainfall for the region. Off by > 50% suggests a FORMAT or unit error.
3. **Peak intensity**: Maximum value should be consistent with IDF curves for the region.
4. **Coverage**: Time series should cover the entire simulation period plus any antecedent conditions.
5. **Gage assignment**: No subcatchment should reference a non-existent rain gage.

## Common Pitfalls

**INTENSITY vs VOLUME mismatch (SILENT ERROR — dt_009)**: The #1 most common SWMM error. If data records mm per 5-min interval (VOLUME) but FORMAT=INTENSITY, SWMM treats each value as mm/hr. A 2.5 mm/5min event (= 30 mm/hr) is interpreted as 2.5 mm/hr, reducing rainfall by 12x. Conversely, if data is mm/hr (INTENSITY) but FORMAT=VOLUME, SWMM treats 30 mm/hr as 30 mm/5min = 360 mm/hr, amplifying by 12x. There is absolutely NO error message. The only symptom is wrong runoff volumes.

**Wrong INTERVAL**: If data is at 5-min intervals but INTERVAL=1:00 (hourly), SWMM reads 12 rows for every hour, misaligning timestamps. Some data points are skipped, others double-counted.

**Missing rain gage in [RAINGAGES]**: If a subcatchment references a rain gage that is not defined, SWMM reports an error at startup. This is at least a detectable error, unlike FORMAT mismatches.

**Gridded source read with the wrong INTERVAL (SILENT — dt_024)**: a 3-hourly series must have `INTERVAL 3:00`. With a design storm's `0:05` left in `[RAINGAGES]`, SWMM holds each value for 5 minutes instead of 3 hours and keeps 1/36 of the rain, with no error. Always take FORMAT and INTERVAL from what `build_rain_timeseries_from_source` printed, and check `Total Precipitation` (mm) in the `.rpt` against `total_mm` in the summary file.

**Rain made from another model's input files (dt_023)**: do not. The former `convert_vic_forcing_to_swmm` tool read column 0 of VIC forcing files as rain; in this server's VIC files that column is air temperature. It was removed on 2026-10-02.

**Daily data from the loader (dt_025)**: `load_daily_forcing` gives one value per day; SWMM needs sub-daily rain. Use the tool above (it calls `load_hourly_forcing`).

**Timezone mismatch**: Rainfall data recorded in local time vs. UTC. A 6-hour timezone offset shifts the hydrograph peak by 6 hours. Always verify timezone consistency between rainfall data and simulation dates.

**Daily rainfall in sub-daily model**: If only daily rainfall totals are available but the SWMM model runs at 5-min timestep, the rainfall must be disaggregated. Simply assigning the daily total to a single timestep creates an artificially intense burst. Use temporal disaggregation (e.g., SCS distribution applied to each day's total).

## Tools Reference

| Tool ID | Script | Purpose |
|---------|--------|---------|
| `create_rain_timeseries` | `tools/s3_rainfall_forcing/create_rain_timeseries.py` | Convert gauge CSV to SWMM format |
| `build_rain_timeseries_from_source` | `tools/s3_rainfall_forcing/build_rain_timeseries_from_source.py` | Rain series straight from CMFD / MSWX / NASA POWER |
| `generate_design_storm` | `tools/s3_rainfall_forcing/generate_design_storm.py` | Create synthetic design storms |
| `validate_rainfall_input` | `tools/s3_rainfall_forcing/validate_rainfall_input.py` | Validate rainfall data and gage config |
