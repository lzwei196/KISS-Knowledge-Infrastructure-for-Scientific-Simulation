# Engine Configuration — Skill Document

> **Stage ID**: s5_engine_config
> **Pipeline order**: 5 of 8
> **Depends on**: s1_crop_params, s2_soil_params, s3_weather_prep, s4_agromanagement

## Purpose

Assemble all input components (crop parameters, soil parameters, weather data, agromanagement) into a PCSE engine object that can execute the WOFOST simulation. This stage requires choosing the correct simulation mode (potential vs water-limited) and creating the ParameterProvider that wraps all parameter dictionaries. The engine class determines which physical processes are simulated and which are ignored.

## Prerequisites

- [ ] Crop parameters loaded and validated (Stage 1)
- [ ] Soil parameters configured and validated (Stage 2) — required only for WLP modes
- [ ] Weather data provider ready (Stage 3)
- [ ] Agromanagement YAML parsed (Stage 4)
- [ ] Simulation mode decided: PP (potential), WLP_FD (water-limited, free drainage), or WLP_CWB (water-limited, classic water balance)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| cropdata | YAMLCropDataProvider | Stage 1 | Crop parameter provider with active crop set |
| soildata | dict | Stage 2 | Soil parameter dictionary (14 keys) |
| sitedata | dict | WOFOST72SiteDataProvider | Site parameters (WAV, CO2, etc.) |
| weather | WeatherDataProvider | Stage 3 | Daily weather data provider |
| agro | list | Stage 4 | Agromanagement list of campaign dicts |
| simulation_mode | string | user | 'PP', 'WLP_FD', or 'WLP_CWB' |

## Procedure

### Step 1: Create site parameters

```python
from pcse.util import WOFOST72SiteDataProvider

# WAV = initial available soil water (cm). Ignored in PP mode.
# CO2 = atmospheric CO2 concentration (ppm). Affects photosynthesis.
sitedata = WOFOST72SiteDataProvider(WAV=20, CO2=400)

# For pre-industrial: CO2=280
# For current (2024): CO2=420
# For RCP8.5 2100: CO2=936
```

### Step 2: Create ParameterProvider

```python
from pcse.base import ParameterProvider

params = ParameterProvider(
    cropdata=cropdata,    # YAMLCropDataProvider object
    soildata=soildata,    # dict with SMW, SMFCF, SM0, etc.
    sitedata=sitedata     # WOFOST72SiteDataProvider object
)
```

**Expected result**: No exception. ParameterProvider wraps all three dictionaries.

**If this fails**: Missing required parameters. Check error message for the specific key. Most common: missing soil parameters when using WLP mode.

### Step 3: Select and instantiate engine class

```python
from pcse.models import Wofost72_PP, Wofost72_WLP_FD

# Choose based on simulation_mode:
if simulation_mode == 'PP':
    engine = Wofost72_PP(params, weather, agro)
elif simulation_mode == 'WLP_FD':
    engine = Wofost72_WLP_FD(params, weather, agro)
elif simulation_mode == 'WLP_CWB':
    from pcse.models import Wofost72_WLP_CWB
    engine = Wofost72_WLP_CWB(params, weather, agro)
else:
    raise ValueError(f"Unknown mode: {simulation_mode}")
```

**Expected result**: Engine instantiates without exception.

**If this fails**:
- `KeyError` on a parameter name → Missing parameter in crop/soil/site data. See dt_008.
- `ValueError` → Parameter value out of expected range.
- Weather date error → Weather data does not cover the campaign start date. See dt_011.

### Step 4: Verify engine readiness

```python
# Check that the engine has been properly initialized
print(f"Engine class: {type(engine).__name__}")
print(f"Start date: {engine.agromanager.start_date}")

# Quick test: can we get a variable?
try:
    dvs = engine.get_variable('DVS')
    print(f"Initial DVS: {dvs}")
except Exception as e:
    print(f"Warning: get_variable failed (normal before first run): {e}")
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| engine object | in-memory | `type(engine).__name__` is 'Wofost72_PP' or 'Wofost72_WLP_FD' etc. |
| ParameterProvider | in-memory | Contains crop + soil + site parameters |

## Validation Checks

1. **Mode matches data availability**: If WLP_FD selected, soil parameters must include SMW, SMFCF, SM0, K0
   - Command: `assert 'SMW' in soildata and 'SMFCF' in soildata`
   - If unexpected: See diagnostic triplet dt_008

2. **Weather covers campaign period**: Weather data first date <= campaign start date
   - Command: `assert weather.first_date <= campaign_start_date`
   - If unexpected: See diagnostic triplet dt_011

3. **CO2 concentration reasonable**: 200-1200 ppm
   - If CO2=0: photosynthesis will be zero. Fatal.

4. **WAV non-negative**: Initial available water >= 0
   - Negative WAV is physically impossible

## Common Pitfalls

> **PITFALL**: Using Wofost72_PP when you want water stress effects
> PP mode ignores all soil water dynamics. Yield will be the theoretical maximum, which can be 2-5x higher than actual water-limited yield. If you want realistic yields, use WLP_FD.
> **Do this instead**: Use Wofost72_WLP_FD for real-world simulations. Reserve PP for computing potential yield benchmarks.
> See diagnostic triplet dt_008.

> **PITFALL**: Missing soil parameters in WLP mode
> Wofost72_WLP_FD requires all 14 soil parameters. Omitting any one causes a `KeyError` during engine initialization. The error message names the missing key but does not explain what it should be.
> **Do this instead**: Use the validated soil parameter dict from Stage 2 which guarantees all 14 keys are present.

> **PITFALL**: Weather data does not cover crop start date
> If the campaign starts on 2000-10-01 but weather data starts on 2001-01-01, the engine will raise an exception. For winter crops, weather must cover autumn of the sowing year.
> **Do this instead**: Ensure weather data starts before the campaign start date.

---

*This skill document is part of the wofost-pcse-knowledge infrastructure.*
*Stage 5 of 8 | Tools: configure_pcse_engine, validate_engine_config | Related triplets: dt_008, dt_011*
