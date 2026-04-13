# Stage 3: Model Execution — Running CWatM

## Purpose

Execute the CWatM simulation after all input data is prepared. This stage covers preflight validation, model execution, progress monitoring, and initial output checking.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| settings.ini | INI text file | Complete configuration (from Stage 0) |
| Meteorological forcing | NetCDF files | Precipitation, temperature, radiation, etc. (from Stage 1) |
| Static data | NetCDF files | Topography, soil, land cover, channels (from Stage 2) |
| Initial conditions | NetCDF (optional) | Warm start state variables |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| discharge_daily.nc | NetCDF | Daily discharge at gauge locations |
| Various output maps | NetCDF | As configured in [OUTPUT] section |
| Console output | Text | Progress, timing, discharge values |
| Initial conditions | NetCDF (optional) | Saved state for warm start |

## Procedure

### Pre-execution Checks

1. **Validate settings file syntax**:
   ```bash
   python run_cwatm.py settings.ini -c
   ```
   This checks all input files exist without running the model.

2. **Check critical settings**:
   - `TemperatureInKelvin` matches input data
   - `precipitation_coversion` matches input units
   - `StepStart` < `SpinUp` < `StepEnd`
   - Output directory exists or is creatable

3. **Verify C++ library**:
   ```python
   import ctypes
   lib = ctypes.cdll.LoadLibrary("cwatm/hydrological_modules/routing_reservoirs/t5_linux.so")
   ```

### Execution

```bash
# Standard run (quiet mode)
python run_cwatm.py settings.ini -q

# Verbose run (shows timestep and discharge)
python run_cwatm.py settings.ini -l

# With timing profiler
python run_cwatm.py settings.ini -t

# Very quiet (no output, for batch runs)
python run_cwatm.py settings.ini -v
```

### Execution Modes

| Flag | Mode | Output |
|------|------|--------|
| (none) | Normal | Date progression |
| `-q` | Quiet | Progress dots |
| `-v` | Very quiet | No progress |
| `-l` | Loud | Step, date, discharge |
| `-t` | Timer | Module execution times |
| `-c` | Check | Input validation only |

### Warm Start

Save state at end of simulation:
```ini
[INITITIAL CONDITIONS]
save_initial = True
initSave = $(FILE_PATHS:PathOut)/init
StepInit = 31/12/2010
```

Load saved state for continuation:
```ini
load_initial = True
initLoad = $(FILE_PATHS:PathOut)/init/initial_2010-12-31.nc
```

### Calibration Mode

For automated calibration, use `mainwarm()` to keep meteorological data in memory:
```python
from cwatm.run_cwatm import mainwarm, parse_args
settings, args = parse_args()
meteo, success, last_dis = main(settings, args)  # First run
success, last_dis = mainwarm(settings, args, meteo)  # Subsequent runs
```

## Verification

1. **Check console output**: Look for error messages, especially:
   - `CWATMError`: Configuration or input data errors
   - `FileNotFoundError`: Missing input files
   - Memory errors: Domain too large for available RAM

2. **Check output files exist**:
   ```bash
   ls -la output/*.nc
   ```

3. **Quick discharge sanity check**:
   ```python
   import netCDF4 as nc
   ds = nc.Dataset("output/discharge_daily.nc")
   q = ds.variables["discharge"][:]
   print(f"Min: {q.min():.2f}, Max: {q.max():.2f}, Mean: {q.mean():.2f} m³/s")
   ```

4. **Runtime expectations** (approximate):
   - 30 arcmin global: ~2 hours per simulation year
   - 30 arcmin Rhine basin: ~5 seconds per year
   - 5 arcmin basin: ~10× slower than 30 arcmin

## Traps

1. **Memory for global runs**: A 30-arcmin global run requires ~8-16 GB RAM. 5-arcmin global requires ~100+ GB. Start with small basins.

2. **SpinUp period too short**: CWatM needs 3-5 years spinup for groundwater equilibration. Output before SpinUp date is discarded but computation still runs.

3. **C++ library mismatch**: The pre-compiled `t5_linux.so` may not work on all Linux distributions. If loading fails, CWatM falls back to pure Python (~100× slower for routing).

4. **MODFLOW coupling**: If `modflow_coupling = True` but MODFLOW libraries are not installed, the model will crash. Ensure `flopy` and `xmipy` are installed.

5. **Output directory permissions**: CWatM creates output files in `OUT_Dir`. Ensure write permissions.

6. **NaN in forcing data**: Missing values in meteorological input cause NaN propagation through all calculations. Pre-fill gaps before running.

## Example

```bash
# Complete execution workflow
cd /path/to/cwatm/

# Step 1: Check inputs
python run_cwatm.py settings_rhine.ini -c
# Expected: "No errors found" or list of issues

# Step 2: Run model
python run_cwatm.py settings_rhine.ini -l
# Expected: Timestep progression with discharge values

# Step 3: Quick validation
python -c "
import netCDF4 as nc
ds = nc.Dataset('output/discharge_daily.nc')
for v in ds.variables:
    if v != 'time':
        d = ds.variables[v][:]
        print(f'{v}: min={d.min():.2f} max={d.max():.2f} mean={d.mean():.2f}')
"
```
