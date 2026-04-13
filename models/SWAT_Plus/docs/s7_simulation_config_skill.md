# Simulation Configuration — Skill Document

> **Stage ID**: s7_simulation_config
> **Pipeline order**: 7 of 9
> **Depends on**: s1_watershed_delineation, s2_hru_definition, s3_weather_preparation, s4_soil_database, s5_landuse_management, s6_calibration_parameters

## Purpose

This stage assembles all input files into a complete, self-consistent TxtInOut directory and configures the master control (file.cio), simulation period (time.sim), and output settings (print.prt). This is the final verification gate before model execution. A single missing file or inconsistent reference in file.cio will cause a runtime crash or silent wrong results.

## Prerequisites

Before starting this stage, verify:

- [ ] All S1-S6 outputs exist in the TxtInOut directory
- [ ] Weather files (S3) cover the full simulation period including warmup years
- [ ] Soil database (S4) has entries for all soil types referenced by HRUs
- [ ] Management schedules (S5) exist for all agricultural land uses
- [ ] Calibration file (S6) has valid parameter adjustments

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| TxtInOut directory | directory | S1-S6 outputs | All SWAT+ input files |
| Simulation period | config | User | Start/end dates, warmup years |
| Output settings | config | User | Which variables to print, at what frequency |
| Basin parameters | config | User / literature | Basin-wide settings (PET method, routing, etc.) |

## Procedure

### Step 1: Configure time.sim

```bash
python tools/s7/configure_time_sim.py
```

time.sim format:
```
time.sim: written by SWAT+ knowledge infrastructure
  day_start    yrc_start    day_end    yrc_end    step
  1            1998         365        2010       0
```

- `day_start`/`day_end`: Julian day (1-365)
- `yrc_start`/`yrc_end`: Calendar year
- `step`: 0 = daily

In print.prt, set `nyskip` for warmup years:
```
  nyskip    day_start    yrc_start    day_end    yrc_end    interval
  2         1            2000         365        2010       1
```

This means: start simulation from 1998, but only start writing output from 2000 (2 years warmup).

**Expected result**: time.sim with valid dates. Weather data must cover yrc_start through yrc_end.

### Step 2: Configure print.prt

```bash
python tools/s7/configure_print_prt.py
```

print.prt controls which output files SWAT+ writes:

```
print.prt: written by SWAT+ knowledge infrastructure
  nyskip    day_start    yrc_start    day_end    yrc_end    interval
  2         1            2000         365        2010       1
  aa_int_cnt
  0
                  daily     monthly   yearly    avann
  basin_wb        y         y         y         y
  basin_nb        n         y         y         y
  basin_ls        n         n         y         y
  basin_psc       n         n         n         n
  basin_aqu       n         y         n         n
  channel_sd      y         y         y         y
  channel_sdmorph n         n         n         n
  aquifer         n         y         n         n
  reservoir       n         n         n         n
  recall          n         n         n         n
  hru_wb          n         n         y         n
  hru_nb          n         n         y         n
  hru_ls          n         n         y         n
  hru_pw          n         n         n         n
  ...
```

**Key output categories**:
- `basin_wb`: Basin water balance (must enable for validation)
- `channel_sd`: Channel discharge and sediment (must enable for discharge comparison)
- `basin_nb`: Basin nutrient balance (enable for water quality)
- `hru_wb/nb/ls`: Per-HRU detail (generates very large files — enable yearly only)

**Expected result**: print.prt with desired output configuration.

### Step 3: Configure codes.bsn and parameters.bsn

codes.bsn controls basin-wide simulation options:
- `pet`: PET calculation method (0=Priestley-Taylor, 1=Penman-Monteith, 2=Hargreaves)
- `rte`: Routing method (0=variable storage, 1=Muskingum)
- `deg`: Channel degradation (0=off, 1=on)
- `wq`: Water quality (0=off, 1=QUAL2E)

parameters.bsn controls basin-wide parameters:
- Nutrient cycling rates, sediment routing, water quality constants

For initial runs, use defaults unless you have specific requirements.

### Step 4: Configure file.cio

```bash
python tools/s7/configure_file_cio.py
```

file.cio is the master control file. It lists all input file categories and their file names. Categories appear in a fixed order — do not rearrange.

**file.cio structure** (each line is a category with its file references):
```
file.cio: written by SWAT+ knowledge infrastructure
simulation        time.sim  print.prt  object.cnt  null  null
basin             codes.bsn  parameters.bsn
climate           weather-wgn.cli  weather-sta.cli  null  atmo.cli
connect           hru.con  rout_unit.con  aquifer.con  chandeg.con  recall.con  exco.con  delr.con  aquifer2d.con  hrd.con  ru.con
hru               hru-data.hru  hru-lte.hru
lsunit            ls_unit.def  ls_unit.ele
aquifer           aquifer.aqu  initial.aqu
channel           channel-lte.cha  hyd-sed-lte.cha  null  null  null  null  null
hydrology         hydrology.hyd  topography.hyd  field.fld
soils             soils.sol  nutrients.sol
landuse           landuse.lum  management.sch  cntable.lum  cons_practice.lum  ovn_table.lum  null
calibration       calibration.cal  cal_parms.cal
```

Use `null` for optional files not needed. Do NOT delete the line — just use `null`.

**Expected result**: file.cio with all required file references resolved.

**If this fails**: See diagnostic triplet dt_001.

### Step 5: Generate object.cnt

object.cnt specifies the count of each spatial object type:

```
object.cnt
  name              num
  hru               245
  lsu               35
  aqu               35
  cha               35
  res               0
  rec               0
  ...
```

Counts must match the actual number of records in the respective data files.

### Step 6: Validate TxtInOut

```bash
python tools/s7/validate_txtinout.py
```

Cross-check everything:
- All files referenced in file.cio exist in TxtInOut
- Object counts in object.cnt match actual record counts
- weather-sta.cli station names match .cli file entries
- HRU soil names match soils.sol entries
- Management schedule names in landuse.lum match management.sch

**Expected result**: All cross-references valid.

**If this fails**: See diagnostic triplets dt_001, dt_009.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| file.cio | `TxtInOut/file.cio` | All referenced files exist |
| time.sim | `TxtInOut/time.sim` | Valid dates, step=0 |
| print.prt | `TxtInOut/print.prt` | At least basin_wb and channel_sd enabled |
| object.cnt | `TxtInOut/object.cnt` | Counts match data files |
| codes.bsn | `TxtInOut/codes.bsn` | Valid method codes |
| parameters.bsn | `TxtInOut/parameters.bsn` | Valid parameter values |

## Validation Checks

1. **File reference resolution**: Every non-null file in file.cio must exist.
   - Command: Parse file.cio and check each filename
   - If missing: See diagnostic triplet dt_001

2. **Time consistency**: Weather data period covers time.sim period (including warmup).
   - If short: SWAT+ reads past end of weather file — undefined behavior

3. **Object count consistency**: object.cnt counts match data file record counts.
   - If wrong: See diagnostic triplet dt_009

4. **Print output enabled**: At least basin_wb and channel_sd have 'y' for daily output.

## Common Pitfalls

> **PITFALL**: Missing file referenced in file.cio
> SWAT+ opens every file listed in file.cio at startup. A single missing file causes an immediate crash with a Fortran "file not found" error.
> **Do this instead**: Run validate_txtinout before every simulation.
> See diagnostic triplet dt_001.

> **PITFALL**: Object count mismatch between object.cnt and data files
> If object.cnt says 245 HRUs but hru-data.hru has 250, SWAT+ may read wrong data or crash with array bounds error.
> **Do this instead**: Generate object.cnt by counting records in data files, not by manual entry.
> See diagnostic triplet dt_009.

> **PITFALL**: Warmup period too short
> With 0 warmup years, initial soil moisture and groundwater storage are arbitrary. The first 1-2 years of output are unreliable but look valid. Including them in performance evaluation inflates PBIAS.
> **Do this instead**: Use at least 2 years warmup (nyskip=2). For arid basins, use 3-5 years.

---

*This skill document is part of the SWAT+ knowledge infrastructure.*
*Stage 7 of 9 | Tools used: configure_file_cio, configure_time_sim, configure_print_prt, validate_txtinout | Related triplets: dt_001, dt_009*
