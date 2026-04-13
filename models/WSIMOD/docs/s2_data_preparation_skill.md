# Stage 2–3: Data Preparation & Forcing Input

## Purpose

Convert raw meteorological and hydrological timeseries data into WSIMOD's
`data_input_dict` format. This is the most error-prone stage because unit
conversions are silent — wrong units produce plausible-looking but wrong results.

## Inputs

| Input               | Format   | Source                    | Units (raw)              |
|---------------------|----------|---------------------------|--------------------------|
| Precipitation       | CSV      | Gauge/ERA5/CMFD           | mm/day                   |
| Temperature         | CSV      | Gauge/ERA5/CMFD           | °C                       |
| Evapotranspiration  | CSV      | Calculated/ERA5           | mm/day                   |
| River flow          | CSV      | Gauge/VIC/CaMa            | m³/s                     |
| Water quality       | CSV      | Monitoring stations        | mg/L (concentration)     |

## Outputs

| Output              | Format          | Units (WSIMOD)          | Notes                    |
|---------------------|-----------------|-------------------------|--------------------------|
| data_input_dict     | Python dict     | (variable, Timestamp)→value | Keys are tuples       |
| Precipitation       | m/timestep      | × MM_TO_M = 1e-3       | From mm/d                |
| Temperature         | °C              | No conversion           | Direct                   |
| ET₀                 | m/timestep      | × MM_TO_M = 1e-3       | From mm/d                |
| Flow                | ML/d or m³/d    | × M3_S_TO_ML_D = 86.4  | From m³/s                |
| Pollutant mass      | kg/timestep     | × MG_L_TO_KG_M3 × vol  | From mg/L                |

## Procedure

1. **Load raw CSV data**:
   ```python
   import pandas as pd
   data = pd.read_csv("timeseries_data.csv")
   data.date = pd.to_datetime(data.date)
   ```

2. **Apply unit conversions** (CRITICAL — these are the #1 source of errors):
   ```python
   from wsimod.core import constants
   # Precipitation: mm → m
   data.loc[data.variable == "precipitation", "value"] *= constants.MM_TO_M
   # ET₀: mm → m
   data.loc[data.variable == "et0", "value"] *= constants.MM_TO_M
   ```

3. **Filter by site** (if multi-site CSV):
   ```python
   data = data.loc[data.site == "my_catchment"]
   ```

4. **Build data_input_dict** — keys must be (variable, Timestamp) tuples:
   ```python
   land_inputs = data.set_index(["variable", "date"]).value.to_dict()
   ```

5. **Validate converted values**:
   - Max precipitation < 0.5 m/d (500 mm/d is extreme but possible)
   - Temperature range: -50 to +50°C
   - ET₀ < 0.015 m/d (15 mm/d is very high)
   - No NaN values in dict

6. **YAML mode** (alternative): Define data loading in settings YAML:
   ```yaml
   data:
     land_data:
       filename: "timeseries_data.csv"
       filters:
         - where: site
           is: my_catchment
       scaling:
         - where: variable
           is: precipitation
           variable: value
           factor: MM_TO_M
       index: [variable, date]
       output: value
       format: dict
   ```

## Verification

- [ ] `max(precip) < 0.5` m/d (if > 1.0, likely still in mm)
- [ ] Temperature in °C range [-50, 50]
- [ ] ET₀ < 0.015 m/d
- [ ] No NaN or missing dates in the dict
- [ ] Dict keys are `(str, Timestamp)` tuples, not `(str, str)`
- [ ] Date range covers entire simulation period

## Traps

| Trap   | Symptom                                      | Fix                                      |
|--------|----------------------------------------------|------------------------------------------|
| dt_001 | Lake/river overflows, flooding everywhere    | Precipitation still in mm — apply ×1e-3  |
| dt_004 | Zero forcing, model runs but no flow         | Dict keys are strings not Timestamps     |
| dt_007 | Decay rates wildly wrong                     | Temperature not in °C (ref = 20°C)       |
| dt_015 | Plants die or infinite ET                    | ET₀ still in mm — apply ×1e-3            |
| dt_013 | KeyError during simulation                   | data_input_dict is empty or dates missing|

## Example

```python
import pandas as pd
from wsimod.core import constants

# Load and convert
data = pd.read_csv("timeseries_data.csv")
data.date = pd.to_datetime(data.date)
data.loc[data.variable == "precipitation", "value"] *= constants.MM_TO_M
data.loc[data.variable == "et0", "value"] *= constants.MM_TO_M

# Verify
precip = data.loc[data.variable == "precipitation", "value"]
assert precip.max() < 0.5, f"Precip max {precip.max()} — likely still in mm!"

# Build dict
land_inputs = data.set_index(["variable", "date"]).value.to_dict()
print(f"Loaded {len(land_inputs)} records, {data.date.nunique()} dates")
```
