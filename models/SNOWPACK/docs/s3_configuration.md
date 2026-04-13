# S3: Configuration

## Purpose

Generate the `.ini` configuration file that controls all aspects of a SNOWPACK
simulation: input/output paths, physical parametrizations, numerical settings,
and output selection. The configuration is organized in INI-format sections.

## Inputs

| Parameter                  | Section            | Description                        | Default       |
|----------------------------|--------------------|------------------------------------|---------------|
| STATION1                   | [Input]            | Station ID (matches .smet/.sno)    | —             |
| METEOPATH                  | [Input]            | Path to input files                | ./input       |
| METEOPATH                  | [Output]           | Path for output files              | ./output      |
| CALCULATION_STEP_LENGTH    | [Snowpack]         | Timestep in **seconds**            | 900           |
| FORCING                    | [Snowpack]         | ATMOS or MASSBAL                   | ATMOS         |
| SW_MODE                    | [Snowpack]         | INCOMING, REFLECTED, or BOTH       | BOTH          |
| ATMOSPHERIC_STABILITY      | [Snowpack]         | Stability correction scheme        | MO_MICHLMAYR  |
| ROUGHNESS_LENGTH           | [Snowpack]         | Aerodynamic roughness (m)          | 0.002         |
| HEIGHT_OF_METEO_VALUES     | [Snowpack]         | Sensor height for T/RH (m)         | 2.0           |
| HEIGHT_OF_WIND_VALUE       | [Snowpack]         | Anemometer height (m)              | 10.0          |
| GEO_HEAT                   | [Snowpack]         | Geothermal flux (W/m²)             | 0.06          |
| VARIANT                    | [SnowpackAdvanced] | Preset: DEFAULT, POLAR, NIED       | DEFAULT       |
| WATERTRANSPORTMODEL_SNOW   | [SnowpackAdvanced] | BUCKET, NIED, RICHARDSEQUATION     | BUCKET        |
| ALBEDO_PARAMETERIZATION    | [SnowpackAdvanced] | LEHNING_2, NIED, etc.              | LEHNING_2     |
| METAMORPHISM_MODEL         | [SnowpackAdvanced] | DEFAULT or NIED                    | DEFAULT       |

## Outputs

A single `.ini` file with sections: [General], [Input], [Output], [Snowpack],
[SnowpackAdvanced], [Filters].

## Procedure

1. **Choose variant** — DEFAULT (Alpine), POLAR (Antarctica/Greenland), NIED (Japan).
2. **Set paths** — Input and output directories.
3. **Configure physics** — Stability, water transport, albedo, metamorphism.
4. **Set output options** — TS_DAYS_BETWEEN (time series interval), PROF_DAYS_BETWEEN.
5. **Add filters** — MeteoIO quality control filters in [Filters] section.
6. **Generate** — Run `generate_config.py`.

## Verification

```bash
# Verify timestep is in seconds (should be 60-3600)
grep CALCULATION_STEP_LENGTH io.ini
# Verify paths exist
grep METEOPATH io.ini
# Verify station ID matches .smet and .sno filenames
grep STATION1 io.ini
```

## Traps

### Timestep in minutes instead of seconds (dt_005) — DEGRADED
`CALCULATION_STEP_LENGTH = 15` means 15 seconds, not 15 minutes. The simulation
runs 60× slower with 60× more output. The results may still be physically
reasonable but waste enormous compute time.

**Detection:** If timestep < 60 seconds, it's likely a minutes→seconds confusion.

### SW_MODE mismatch with available data (dt_007) — SILENT
Setting `SW_MODE = BOTH` when RSWR is not in the SMET file causes the model
to use albedo = 0 (or nodata), absorbing all shortwave radiation. The snowpack
melts too fast with no error message.

**Prevention:** Match SW_MODE to the radiation fields actually present in .smet.

### FORCING = ATMOS with missing radiation (dt_008) — DEGRADED
ATMOS mode requires ISWR, ILWR, VW, and RH for the full energy balance.
If ILWR is missing, the model assumes zero incoming longwave → severe cold bias.
Use MASSBAL mode if only temperature and precipitation are available.

### Height of wind measurement (dt_006) — SILENT
If `HEIGHT_OF_WIND_VALUE = 2.0` but the anemometer is actually at 10 m, the
Monin-Obukhov correction underestimates wind speed at the surface, reducing
both sensible heat flux and snow erosion rates.

## Example

```bash
# Default Alpine configuration
python tools/generate_config.py \
    --output io.ini \
    --station_id WFJ2 \
    --meteo_path ./input \
    --output_path ./output \
    --variant DEFAULT \
    --calculation_step 900 \
    --forcing ATMOS \
    --sw_mode BOTH \
    --height_meteo 2.0 \
    --height_wind 10.0

# Polar variant (Antarctica)
python tools/generate_config.py \
    --output io_polar.ini \
    --station_id DOME_C \
    --meteo_path ./input \
    --output_path ./output \
    --variant POLAR \
    --calculation_step 900 \
    --sw_mode INCOMING \
    --geo_heat 0.0
```
