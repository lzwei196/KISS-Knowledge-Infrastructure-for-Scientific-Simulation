# Rainfall Forcing Preparation — Skill Document

> **Stage ID**: s3_rainfall_forcing
> **Pipeline order**: 3 of 7
> **Depends on**: none (can run in parallel with S1 and S2)

## Purpose

Rainfall is the primary driver of stormwater runoff in SWMM. This stage prepares rainfall time series from historical gauge data, gridded model forcing (VIC/HydroCraft), or synthetic design storms, and configures rain gages that assign rainfall to subcatchments.

The rainfall forcing stage has the highest potential for SILENT ERRORS in the entire SWMM workflow. Two critical issues dominate:

1. **FORMAT mismatch** (INTENSITY vs VOLUME): If the rain gage FORMAT does not match how the data is encoded, runoff volumes are wrong by a factor proportional to the recording interval. There is NO error message.
2. **Unit mismatch**: If FLOW_UNITS=CMS but rainfall is in inches (or vice versa), SWMM applies the wrong depth-to-volume conversion. There is NO error message.

This stage must be completed with extreme attention to data conventions.

## Prerequisites

Before starting this stage, verify:

- [ ] Rainfall source data is available (gauge records, VIC forcing, or design storm parameters)
- [ ] Recording interval is known (5-min, 15-min, hourly, daily)
- [ ] Data convention is known: is each value an instantaneous rate (mm/hr) or accumulated depth (mm/interval)?
- [ ] FLOW_UNITS has been decided (CFS or CMS) — this determines whether rainfall is in inches or mm
- [ ] Simulation period is defined (start/end dates)
- [ ] Python environment has: pandas, numpy

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Rainfall data | file | Gauge CSV, VIC forcing, or design parameters | Raw precipitation data |
| Data format | string | Data documentation | 'intensity' (rate, mm/hr) or 'volume' (depth per interval, mm) |
| Recording interval | number | Data documentation | Minutes between measurements |
| FLOW_UNITS | string | Model configuration | CFS (rain in inches) or CMS (rain in mm) |
| VIC forcing dir | directory | HydroCraft output | For VIC-to-SWMM conversion (optional) |
| VIC grid NC | file | HydroCraft output | For coordinate mapping (optional) |

## Procedure

### Step 1: Determine Rainfall Data Source

Three main sources, in order of preference:

**Historical gauge data** (best for calibration/validation):
- Actual measurements from rain gauges at or near the study area
- Must verify recording interval and format convention
- May have gaps that need filling

**VIC/HydroCraft forcing** (best for coupled modeling):
- Consistent with the upstream VIC simulation
- 3-hourly or hourly timestep, gridded
- Requires spatial mapping from VIC grid to SWMM rain gages
- Use the `convert_vic_forcing_to_swmm` tool

**Design storms** (best for drainage design):
- Synthetic hyetographs for specific return periods
- SCS Type II (most common in eastern US), Chicago storm, constant intensity
- No calibration possible — design only
- Use the `generate_design_storm` tool

### Step 2: Create Rainfall Time Series

#### From historical gauge data:

```bash
python tools/s3_rainfall_forcing/create_rain_timeseries.py \
  --rainfall_csv data/rainfall/gauge_001.csv \
  --datetime_col datetime \
  --value_col rainfall_mm \
  --data_format volume \
  --interval_minutes 60 \
  --output_file outputs/swmm_run/rainfall/rain_gauge1.dat
```

SWMM TIMESERIES format:
```
;Rainfall time series for Gauge 1
;Date        Time       Value
01/15/2020   00:00:00   0.0
01/15/2020   01:00:00   2.3
01/15/2020   02:00:00   5.1
01/15/2020   03:00:00   8.7
```

Date format: MM/DD/YYYY. Time format: HH:MM:SS. Value in mm (CMS) or inches (CFS).

#### From VIC forcing:

```bash
python tools/s3_rainfall_forcing/convert_vic_forcing_to_swmm.py \
  --vic_forcing_dir outputs/vic_run/vic_temp/forcing/forcing_final \
  --forcing_prefix basin_0.25deg_ \
  --subcatchment_shapefile outputs/swmm_run/subcatchments/subcatchments.shp \
  --vic_grid_nc outputs/vic_run/vic_temp/grid/basin_grid.nc \
  --output_format intensity \
  --output_dir outputs/swmm_run/rainfall/
```

VIC forcing files contain precipitation as the 5th column (0-indexed col 4), in mm per timestep (typically 3 hours). To convert to SWMM:
- For FORMAT=VOLUME: keep as mm per interval, set RAINGAGE INTERVAL = 3:00 (3 hours)
- For FORMAT=INTENSITY: divide by 3 to get mm/hr, set RAINGAGE INTERVAL = 3:00

#### Design storm:

```bash
python tools/s3_rainfall_forcing/generate_design_storm.py \
  --storm_type scs_type_II \
  --total_depth_mm 100 \
  --duration_hours 24 \
  --timestep_minutes 5 \
  --output_file outputs/swmm_run/rainfall/design_storm_100yr.dat
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
- 3-hourly VIC forcing: `3:00`

### Step 4: Assign Rain Gages to Subcatchments

Every subcatchment in `[SUBCATCHMENTS]` must reference a valid rain gage. Assignment methods:
- **Nearest gage**: Each subcatchment uses the closest rain gage
- **Single gage**: All subcatchments use the same gage (for small study areas)
- **Thiessen weights**: Not directly supported in SWMM — use area-weighted average time series

### Step 5: Validate Rainfall Input

```bash
python tools/s3_rainfall_forcing/validate_rainfall_input.py \
  --timeseries_files '["outputs/swmm_run/rainfall/rain_gauge1.dat"]' \
  --raingage_config '{"RG1": {"format": "VOLUME", "interval": "1:00"}}' \
  --flow_units CMS
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

**VIC forcing unit conversion**: VIC stores precipitation as mm per timestep. For 3-hourly VIC forcing:
- SWMM FORMAT=VOLUME, INTERVAL=3:00 → use raw VIC values (mm per 3 hours) ← **recommended**
- SWMM FORMAT=INTENSITY, INTERVAL=3:00 → divide VIC values by 3 to get mm/hr

**Timezone mismatch**: Rainfall data recorded in local time vs. UTC. A 6-hour timezone offset shifts the hydrograph peak by 6 hours. Always verify timezone consistency between rainfall data and simulation dates.

**Daily rainfall in sub-daily model**: If only daily rainfall totals are available but the SWMM model runs at 5-min timestep, the rainfall must be disaggregated. Simply assigning the daily total to a single timestep creates an artificially intense burst. Use temporal disaggregation (e.g., SCS distribution applied to each day's total).

## Tools Reference

| Tool ID | Script | Purpose |
|---------|--------|---------|
| `create_rain_timeseries` | `tools/s3_rainfall_forcing/create_rain_timeseries.py` | Convert gauge CSV to SWMM format |
| `convert_vic_forcing_to_swmm` | `tools/s3_rainfall_forcing/convert_vic_forcing_to_swmm.py` | Map VIC forcing to SWMM rain gages |
| `generate_design_storm` | `tools/s3_rainfall_forcing/generate_design_storm.py` | Create synthetic design storms |
| `validate_rainfall_input` | `tools/s3_rainfall_forcing/validate_rainfall_input.py` | Validate rainfall data and gage config |
