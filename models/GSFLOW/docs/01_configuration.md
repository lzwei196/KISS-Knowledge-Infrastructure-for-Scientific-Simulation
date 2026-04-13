# Stage 0: Configuration

## Purpose
Create a GSFLOW control file that defines the simulation period, model mode,
input/output file paths, module selections, and output variable specifications.
The control file is the master configuration — everything flows from it.

## Inputs
- Basin name and identifiers
- Simulation period (start/end dates)
- Model mode: GSFLOW5 (coupled), PRMS5 (surface only), or MODFLOW (GW only)
- Paths to data file, parameter files, MODFLOW name file
- Module selections (temperature, precipitation, ET, runoff, routing)
- Output variable selections

## Outputs
- `gsflow.control` — GSFLOW control file (plain text, `####`-delimited)

## Procedure

1. **Choose model mode:**
   - `GSFLOW5`: Full coupled simulation (requires both PRMS and MODFLOW inputs)
   - `PRMS5`: Surface-water only (no MODFLOW grid needed)
   - `MODFLOW`: Groundwater only (no PRMS parameters needed)

2. **Set simulation period:**
   - `start_time`: 6 integers (year, month, day, hour, minute, second)
   - `end_time`: same format
   - For GSFLOW mode, also set `modflow_time_zero` to 1 day before start_time

3. **Select climate modules:**
   - For pre-processed gridded data (CMFD, MSWX): use `climate_hru` for all climate modules
   - For station data: use `temp_1sta_laps`, `precip_1sta_laps`, `ddsolrad`
   - For multiple stations: use `temp_dist2`, `precip_dist2`

4. **Specify I/O paths:**
   - All paths are relative to the control file location
   - Use forward slashes (/) even on Windows
   - Ensure output directories exist before running

5. **Configure output:**
   - Set `basinOutON_OFF = 1` for basin-level CSV output
   - List variables in `basinOutVar_names`
   - Set frequency: 1=daily, 2=monthly, 6=yearly

## Verification
- Control file contains `model_mode`, `start_time`, `end_time`
- All referenced input files exist at their specified paths
- `modflow_time_zero` < `start_time` (for GSFLOW mode)
- `####` delimiters are properly placed between parameter blocks
- Run `gsflow -print control_file` to check for parsing errors

## Traps
- **Path separators:** Windows `\` must be changed to `/` on Linux
- **modflow_time_zero:** Must be before start_time, or GSFLOW aborts
- **Module mismatch:** Using `climate_hru` module requires .day files specified
  via `tmax_day`, `tmin_day`, etc. Using station modules requires .data file
- **Missing delimiter:** Every parameter block must end with `####`
- **Data type codes:** 1=integer, 2=real, 4=string. Wrong code → silent parse error

## Example
```bash
python build_control_file.py \
    --output ./control/gsflow.control \
    --mode PRMS5 \
    --start-date 1980-10-01 \
    --end-date 1990-09-30 \
    --param-files ./input/prms/prms.params \
    --day-files ./input/prms/tmax.day,./input/prms/tmin.day,./input/prms/precip.day,./input/prms/swrad.day \
    --temp-module climate_hru \
    --precip-module climate_hru \
    --output-vars basin_cfs,basin_ppt,basin_actet
```
