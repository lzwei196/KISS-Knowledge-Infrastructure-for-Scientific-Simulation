# Stage 2: Weather Data Preparation

## Purpose

Convert meteorological observations or forecasts into Cell2Fire Weather.csv format. The weather file drives fire behavior — incorrect units silently produce wrong results.

## Inputs

| Variable | Common Sources | Source Units | C2F Unit |
|----------|---------------|-------------|----------|
| Wind speed | Weather station, ERA5, GFS | m/s | **km/h** |
| Wind direction | Weather station | degrees | degrees (meteorological convention) |
| Temperature | ERA5, station | K or °C | **°C** (FBP only) |
| Relative humidity | ERA5, station | fraction or % | **%** (FBP only) |
| Precipitation | ERA5, station | m/s or mm/hr | **mm** (FBP only) |
| FWI indices | CFFDRS system | dimensionless | dimensionless (FBP only) |

## Outputs

### Scott & Burgan / Kitral format (`--sim S` or `--sim K`)

```csv
Instance,datetime,WS,WD,FireScenario
Jaime,2001-10-16 13:00,10,180.0,2
```

| Column | Type | Unit | Range |
|--------|------|------|-------|
| Instance | string | — | Scenario name |
| datetime | string | YYYY-MM-DD HH:MM or M/D/YY HH:MM | Hourly timestamps |
| WS | float | km/h | 0-200 |
| WD | float | degrees | 0-360 |
| FireScenario | int | — | 1 (low), 2 (moderate), 3 (extreme) |

### Canadian FBP format (`--sim C`)

```csv
Scenario,datetime,APCP,TMP,RH,WS,WD,FFMC,DMC,DC,ISI,BUI,FWI
JCB,2001-10-16 13:00,0.0,17.7,20,21,235,90.5,64,535,13.4,99,37.9
```

| Column | Type | Unit | Range |
|--------|------|------|-------|
| Scenario | string | — | Scenario name |
| datetime | string | YYYY-MM-DD HH:MM | Hourly timestamps |
| APCP | float | mm | ≥ 0 |
| TMP | float | °C | -40 to 50 |
| RH | int | % | 0-100 |
| WS | int | km/h | 0-200 |
| WD | int | degrees | 0-360 |
| FFMC | float | dimensionless | 0-101 |
| DMC | int | dimensionless | 0-300+ |
| DC | int | dimensionless | 0-800+ |
| ISI | float | dimensionless | 0-100+ |
| BUI | int | dimensionless | 0-300+ |
| FWI | float | dimensionless | 0-150+ |

## Procedure

### Step 1: Obtain weather data

- Fire weather observations from nearest station
- Reanalysis data (ERA5, MERRA-2) for historical events
- Forecast data (GFS, ECMWF) for operational use

### Step 2: Convert units

Use `convert_weather_to_c2f.py`:

```bash
python convert_weather_to_c2f.py \
    --input raw_met.csv --output Weather.csv \
    --model S --scenario-name "Fire2023" --fire-scenario 2
```

The tool auto-detects units:
- If max wind speed < 60 → assumes m/s, converts to km/h (×3.6)
- If max temperature > 100 → assumes Kelvin, converts to °C (-273.15)
- If max RH ≤ 1.0 → assumes fraction, converts to % (×100)

### Step 3: Compute FWI indices (FBP model only)

If using `--sim C`, the Canadian Fire Weather Index (FWI) System indices must be computed:
1. Start with noon-hour weather observations (temperature, RH, wind speed, 24h precipitation)
2. Compute FFMC, DMC, DC using the standard CFFDRS equations
3. Derive ISI from FFMC and wind speed
4. Derive BUI from DMC and DC
5. Derive FWI from ISI and BUI

### Step 4: Choose fire scenario (S&B only)

The `FireScenario` column (1-3) controls fuel moisture thresholds:
- **1**: Low fire weather — high moisture, low spread
- **2**: Moderate fire weather
- **3**: Extreme fire weather — low moisture, maximum spread

This is separate from `--fmc` (foliar moisture content).

### Step 5: Create Weathers directory (for random weather)

For `--weather random`, place multiple Weather files:
```
instance/Weathers/
├── Weather1.csv
├── Weather2.csv
└── Weather3.csv
```

Cell2Fire randomly selects a weather file for each simulation.

## Verification

1. **Wind speed range**: Should be 0-200 km/h. If max < 5, likely still in m/s.
2. **Wind direction range**: 0-360 degrees.
3. **Temperature range**: -40 to +50°C. If > 100, likely in Kelvin.
4. **RH range**: 0-100%. If < 1, likely fraction.
5. **FFMC range**: 0-101 (above ~80 = fire weather).
6. **Hourly timestamps**: Check datetime is parsed correctly.
7. **Number of rows**: Must cover the entire simulation period.

## Traps

| Trap | Symptom | Impact | Fix |
|------|---------|--------|-----|
| WS in m/s instead of km/h | Fire barely spreads | ROS ~3.6× too low | Multiply by 3.6 |
| WD math convention (TO) | Fire spreads wrong direction | Complete direction error | Add 180, mod 360 |
| TMP in K instead of °C | FBP indices nonsensical | FFMC/ISI wildly wrong | Subtract 273.15 |
| RH as fraction (0-1) | Extreme fire behavior | FBP thinks air is bone dry | Multiply by 100 |
| Missing FWI indices | FBP model crashes or defaults | Unpredictable results | Compute from CFFDRS |
| Wrong scenario number | Too much/little burning | Burned area 10× difference | Match to fire weather severity |

## Example

Converting ERA5 data for Scott & Burgan:
```python
from convert_weather_to_c2f import convert_weather

result = convert_weather(
    input_path="era5_hourly.csv",
    output_path="instance/Weather.csv",
    model="S",
    scenario_name="ERA5_fire",
    fire_scenario=2,
    auto_units=True,
)
print(f"Converted {result['n_rows']} rows")
print(f"Conversions: {result['conversions_applied']}")
```
