# Stage 0: Configuration and Setup

## Purpose

Initialize a COSIPY simulation by selecting the glacier site, simulation period, forcing data source, and physical parameterizations. This stage produces the `config.toml` and `constants.toml` files that control all subsequent stages.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Glacier location | User / RGI inventory | Lat/lon coordinates |
| Simulation period | User | ISO 8601 dates |
| Forcing data source | ERA5 / AWS / WRF | Determines conversion pipeline |
| Physical knowledge | Literature / calibration | Parameterization choices |

## Outputs

| Output | Path | Format |
|--------|------|--------|
| `config.toml` | Working directory | TOML |
| `constants.toml` | Working directory | TOML |
| `utilities_config.toml` | Working directory | TOML |
| `slurm_config.toml` | Working directory (if SLURM) | TOML |

## Procedure

1. **Generate template configs**: Run `cosipy-setup` or `python -m cosipy.utilities.setup_cosipy.setup_cosipy` to create template TOML files.

2. **Edit config.toml**:
   - Set `time_start` and `time_end` (ISO 8601 format: "YYYY-MM-DDTHH:MM")
   - Set `data_path` to the base data directory
   - Set `input_netcdf` relative to `data_path/input/`
   - Set `output_prefix` for output file naming
   - Set `WRF = true` if using WRF input (changes dimension names)
   - Set `workers` for parallel execution (0 = all cores)
   - Set `full_field = true` if layer-resolved output is needed

3. **Edit constants.toml**:
   - Set `dt` to match input data time step in seconds
   - Choose albedo method: `Oerlemans98` (recommended) or `Bougamont05`
   - Set initial conditions (snowheight, glacier height, temperature)
   - Adjust remeshing parameters if needed

4. **Edit utilities_config.toml** (for data conversion):
   - Set variable name mappings for aws2cosipy
   - Set lapse rates for elevation correction
   - Set station information (altitude, latitude)

## Verification

```bash
# Check config files parse correctly
python -c "
import tomllib
with open('config.toml', 'rb') as f: cfg = tomllib.load(f)
with open('constants.toml', 'rb') as f: cst = tomllib.load(f)
print('Config OK:', list(cfg.keys()))
print('Constants OK:', list(cst.keys()))
print('Period:', cfg['SIMULATION_PERIOD']['time_start'], 'to', cfg['SIMULATION_PERIOD']['time_end'])
print('dt:', cst['GENERAL']['dt'], 's')
"
```

## Traps

1. **time_start/time_end must be within input data range**: If the simulation period extends beyond the forcing data, COSIPY selects an empty time slice and produces all-NaN output without error.

2. **dt must match input time step**: Default 3600s (1 hour). If input is 3-hourly, set dt=10800. Mismatch causes all mass balance terms to be wrong by a constant factor.

3. **workers=0 means "use all cores"**: Not zero workers. This is a TOML quirk — COSIPY converts 0 to None (= auto-detect).

4. **WRF flag changes dimension names**: If WRF=true, COSIPY looks for `south_north`/`west_east` dimensions instead of `lat`/`lon`. Wrong setting causes KeyError on startup.

## Example

```toml
# config.toml for Zhadang Glacier point model
[SIMULATION_PERIOD]
time_start = "2009-01-01T06:00"
time_end = "2009-01-10T00:00"

[FILENAMES]
data_path = "./data/"
input_netcdf = "Zhadang/Zhadang_ERA5_2009.nc"
output_prefix = "Zhadang_ERA5"

[DIMENSIONS]
WRF = false
northing = "lat"
easting = "lon"

[PARALLELIZATION]
workers = 0
```
