# S6: Output Extraction and Analysis

## Purpose

Parse SNOWPACK output files (.met time series, .pro profiles) into analysis-
ready CSV format. Extract selected variables, compute derived quantities,
and prepare data for validation, visualization, and inter-model comparison.

## Inputs

| Input           | Description                                     |
|-----------------|-------------------------------------------------|
| station.met     | SNOWPACK time series output                      |
| station.pro     | SNOWPACK profile output (optional)               |
| Variables list  | Comma-separated list of variables to extract      |

## Outputs

| Output             | Description                                   |
|--------------------|-----------------------------------------------|
| timeseries.csv     | Datetime + selected variables in clean CSV      |
| profiles.csv       | Layer data at selected timesteps (from .pro)    |

## Procedure

1. **Identify output files** — Check output directory for .met and .pro files.
2. **Select variables** — Choose from the available output fields.
3. **Parse .met file** — Use `parse_output.py` to extract time series.
4. **Optionally parse .pro** — Extract layer profiles if needed.
5. **Compute derived quantities** — e.g., daily averages, cumulative SWE.
6. **Verify** — Check for nodata contamination, correct time range.

## Key Output Variables

### Energy fluxes (W/m²)

| Variable | Description                      | Typical range |
|----------|----------------------------------|---------------|
| ISWR     | Incoming shortwave radiation     | 0–1200        |
| OSWR     | Outgoing (reflected) shortwave   | 0–1000        |
| ILWR     | Incoming longwave radiation      | 100–400       |
| OLWR     | Outgoing longwave radiation      | 150–350       |
| qs       | Sensible heat flux               | -100–200      |
| ql       | Latent heat flux                 | -150–100      |
| qg       | Ground heat flux                 | -20–20        |
| qr       | Rain energy flux                 | 0–50          |

### Mass balance (kg/m² per output interval)

| Variable    | Description                          | Typical range |
|-------------|--------------------------------------|---------------|
| MS_HNW      | New snow precipitation (solid)       | 0–20          |
| MS_RAIN     | Rain precipitation (liquid)          | 0–50          |
| MS_EVAP     | Evaporation/sublimation mass loss    | -5–0          |
| MS_RUNOFF   | Liquid water runoff from snow base   | 0–50          |
| SWE         | Snow water equivalent (state)        | 0–2000        |

### Snow state

| Variable   | Description                     | Unit    | Typical range |
|------------|---------------------------------|---------|---------------|
| HS         | Total snow height               | m       | 0–10          |
| TA         | Air temperature                 | K       | 230–320       |
| TSS        | Snow surface temperature        | K       | 230–273.15    |
| TSG        | Ground surface temperature      | K       | 260–290       |
| Albedo     | Surface albedo                  | 0–1     | 0.1–0.95      |
| RHO_mean   | Mean snow density               | kg/m³   | 50–600        |

## Verification

```bash
# Quick statistics
python -c "
import pandas as pd
df = pd.read_csv('results/station_ts.csv', parse_dates=['datetime'])
print(df.describe())
print('Period:', df['datetime'].min(), 'to', df['datetime'].max())
"

# Check for unrealistic values
python -c "
import pandas as pd
df = pd.read_csv('results/station_ts.csv')
if 'HS' in df.columns:
    assert df['HS'].max() < 50, 'HS > 50m is unrealistic'
    assert df['HS'].min() >= 0, 'Negative HS'
if 'SWE' in df.columns:
    assert df['SWE'].min() >= 0, 'Negative SWE'
print('Basic sanity checks passed')
"
```

## Traps

### Nodata values not filtered (dt_009)
If the nodata value in output (typically -999) is not recognized by the parser,
it gets included in statistics. Mean HS with a single -999 value will be
heavily skewed negative.

**Prevention:** `parse_output.py` replaces the declared nodata value with NaN.

### Mixing up output timestep with model timestep
The .met output interval (TS_DAYS_BETWEEN) may differ from the model calculation
timestep (CALCULATION_STEP_LENGTH). Mass fluxes in .met are accumulated over
the output interval, not the calculation timestep.

### Profile output format confusion
The .pro file format uses numeric codes (0500, 0501, etc.) as line prefixes.
These are not data values — they are format markers. Parsing .pro files as
simple tab-separated data will produce garbage.

## Example

```bash
# Extract key time series variables
python tools/parse_output.py \
    --input output/MST96.met \
    --output results/MST96_timeseries.csv \
    --variables HS,SWE,TA,TSS,ISWR,ILWR,qs,ql,MS_HNW,MS_RAIN,MS_RUNOFF,Albedo

# Extract profiles
python tools/parse_output.py \
    --input output/MST96.pro \
    --output results/MST96_profiles.csv \
    --file_type pro \
    --variables T,Rho,rg
```
