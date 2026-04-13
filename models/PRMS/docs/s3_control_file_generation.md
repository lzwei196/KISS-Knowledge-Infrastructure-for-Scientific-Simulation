# Stage 3: Control File Generation

## Purpose

Generate the PRMS control file that ties together all input files, simulation settings, module selections, and output options.

## Inputs

- File paths: parameter file, data file, CBH files
- Simulation period: start/end dates
- Module selections from Stage 0
- Output preferences (CSV, NetCDF, summary options)

## Outputs

- PRMS control file (plain text, `####`-delimited format)

## Procedure

### Step 1: Gather file paths

```python
files = {
    "param_file": "/prms/input/prms.params",
    "data_file": "/prms/input/prms.data",
    "tmax_day": "/prms/input/tmax.cbh",      # if using climate_hru
    "tmin_day": "/prms/input/tmin.cbh",
    "precip_day": "/prms/input/precip.cbh",
}
```

### Step 2: Set simulation period

- `start_time`: array of 6 integers [year, month, day, hour, min, sec]
- `end_time`: same format
- `initial_deltat`: 24.0 (hours — always 24 for daily PRMS)

### Step 3: Select modules

Each module is a string-type control variable:

```
####
temp_module
1
4
climate_hru
```

### Step 4: Configure output

| Control Variable | Type | Default | Description |
|-----------------|------|---------|-------------|
| csvON_OFF | int | 1 | Enable CSV summary output |
| basinOutON_OFF | int | 1 | Basin-level output |
| nhruOutON_OFF | int | 0 | Per-HRU output (can be large) |
| statsON_OFF | int | 0 | Statvar output |
| model_output_file | string | prms.out | Path for model output |
| csv_output_file | string | prms.csv | Path for CSV output |

### Step 5: Write control file

```python
from tools.generate_control_file import write_control_file
write_control_file("control", variables)
```

## Verification

- [ ] Control file starts with info string (first line)
- [ ] All `####` delimiters are correct (exactly 4 #)
- [ ] Type codes are correct (1=long, 2=float, 3=double, 4=string)
- [ ] start_time has 6 values
- [ ] end_time has 6 values
- [ ] All file paths exist (param_file, data_file, CBH files)
- [ ] Module names are spelled correctly

## Traps

### 1. Type code mismatch

Using type code 1 (long) for a string path or vice versa causes silent failures. File paths are ALWAYS type 4.

### 2. Wrong delimiter count

The control file uses `####` (4 hash marks). The data file uses `####` too. The CBH file uses `########` (8+). Don't mix them up.

### 3. start_time is 6 longs, not a string

```
####
start_time
6          <- size = 6
1          <- type = 1 (long integer)
1980       <- year
10         <- month
1          <- day
0          <- hour
0          <- minute
0          <- second
```

### 4. File path encoding

File paths in the control file should be relative to the working directory where PRMS is executed, or absolute paths. No quotes needed.

### 5. initial_deltat must be 24.0

PRMS is a daily model. `initial_deltat = 24.0` (hours). If set to 1.0, the model tries hourly steps and fails.

## Example

```bash
python tools/generate_control_file.py \
    --output_file /prms/control \
    --param_file /prms/input/prms.params \
    --data_file /prms/input/prms.data \
    --start_date 1980-10-01 \
    --end_date 2010-09-30 \
    --cbh_dir /prms/input \
    --temp_module climate_hru \
    --precip_module climate_hru \
    --et_module potet_jh
```
