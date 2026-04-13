# Stage 0: Configuration — Settings File Setup

## Purpose

Create and configure the CWatM settings file (`.ini` format) that controls all aspects of the simulation: domain definition, time period, input data paths, model options, calibration parameters, and output specifications.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Study area definition | User / GIS | Bounding box or mask map (NetCDF/PCRaster) |
| Simulation period | User | DD/MM/YYYY dates |
| Input data paths | User / data server | Directory paths |
| Gauge locations | User / GRDC | Coordinates or map file |
| Model options | User | Boolean flags |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| settings.ini | INI text file | Complete CWatM configuration |

## Procedure

1. **Choose a template**: Start from `Tutorials/06_Watercycle/settings_CWatM_template_30min.ini` (most complete) or `Tutorials/01_Turn-ON/settings_Rhine-30min_Tutorial-1.ini` (minimal).

2. **Set file paths**: Configure `[FILE_PATHS]` section with paths to input data:
   ```ini
   [FILE_PATHS]
   PathRoot = /path/to/cwatm/
   PathOut = /path/to/output/
   PathMaps = /path/to/static_maps/
   PathMeteo = /path/to/meteo_forcing/
   ```

3. **Define domain**: Set `[MASK_OUTLET]` with mask map and gauge locations:
   ```ini
   [MASK_OUTLET]
   MaskMap = $(FILE_PATHS:PathMaps)/areamaps/mask.map
   Gauges = 6.25 51.75    # lon lat of gauge station
   ```

4. **Set time period**: Configure dates in DD/MM/YYYY format:
   ```ini
   [TIME-RELATED_CONSTANTS]
   StepStart = 01/01/1990
   SpinUp = 01/01/1995
   StepEnd = 31/12/2010
   ```

5. **Configure meteorological inputs**: Set paths and conversion factors:
   ```ini
   [METEO]
   PrecipitationMaps = $(FILE_PATHS:PathMeteo)/pr*
   TavgMaps = $(FILE_PATHS:PathMeteo)/tas*
   precipitation_coversion = 86.4   # kg/m²/s to m/day
   evaporation_coversion = 1.00
   ```

6. **Enable/disable features**: Set `[OPTIONS]` flags:
   ```ini
   [OPTIONS]
   TemperatureInKelvin = True
   calc_evaporation = True       # Penman-Monteith internally
   includeIrrigation = True
   includeWaterDemand = True
   includeWaterBodies = True
   includeRouting = True
   ```

7. **Set calibration parameters**: Initial values in `[CALIBRATION]`:
   ```ini
   [CALIBRATION]
   SnowMeltCoef = 0.004
   crop_correct = 1.0
   soildepth_factor = 1.0
   arnoBeta_add = 0.2
   recessionCoeff_factor = 5.0
   manningsN = 1.0
   ```

8. **Configure outputs**: Specify variables and temporal aggregation:
   ```ini
   [OUTPUT]
   OUT_Dir = $(FILE_PATHS:PathOut)
   OUT_TSS_Daily = discharge
   OUT_TSS_MonthAvg = discharge
   OUT_MAP_MonthAvg = discharge, totalET, baseflow
   ```

## Verification

- Parse the settings file with Python's `configparser` to check syntax
- Verify all referenced input files exist using `python run_cwatm.py settings.ini -c`
- Confirm date format is DD/MM/YYYY (NOT YYYY-MM-DD)
- Confirm `precipitation_coversion` matches actual input units

## Traps

1. **Date format**: CWatM uses DD/MM/YYYY, not ISO format. Using 2010-01-31 will be misinterpreted.

2. **Variable substitution**: `$(SECTION:KEY)` syntax requires exact section and key names (case-sensitive for keys).

3. **TemperatureInKelvin mismatch**: If set incorrectly, all temperature-dependent processes (snow, ET) produce wrong results with no error message.

4. **precipitation_coversion spelling**: Note the typo in the original CWatM code — it's `coversion`, not `conversion`. Using the correct spelling will cause a silent error.

5. **SpinUp date**: Must be between StepStart and StepEnd. Output is only written after SpinUp.

## Example

```ini
[FILE_PATHS]
PathRoot = /data/cwatm/
PathOut = $(PathRoot)/output
PathMaps = $(PathRoot)/cwatm_input30min
PathMeteo = $(PathRoot)/climate/ERA5

[OPTIONS]
TemperatureInKelvin = True
calc_evaporation = True
includeWaterBodies = True
includeRouting = True

[MASK_OUTLET]
MaskMap = $(FILE_PATHS:PathMaps)/areamaps/rhine30min.map
Gauges = 6.25 51.75

[TIME-RELATED_CONSTANTS]
StepStart = 01/01/1990
SpinUp = 01/01/1995
StepEnd = 31/12/2010

[METEO]
PrecipitationMaps = $(FILE_PATHS:PathMeteo)/pr*
TavgMaps = $(FILE_PATHS:PathMeteo)/tas*
precipitation_coversion = 86.4

[OUTPUT]
OUT_Dir = $(FILE_PATHS:PathOut)
OUT_TSS_Daily = discharge
```
