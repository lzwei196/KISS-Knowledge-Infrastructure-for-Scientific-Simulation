# AquaCrop-OSPy Simulation Workflow

## Pipeline Overview

```
S1 Crop Selection ──────────┐
S2 Soil Profile ─── S4 IWC ─┤
S3 Weather Prep ────────────┤
S5 Irrigation Mgmt ────────┼── S7 Model Assembly ── S8 Execution ── S9 Output ── S10 Water Productivity
S6 Field Management ───────┘
```

**Parallelism**: S1, S2, S3, S5, S6 are independent and can run in parallel. S4 depends on S2. S7 waits for all of S1-S6.

**Runtime**: Typical single-season simulation completes in < 1 second. Multi-year with daily output: ~1 minute. Deficit irrigation optimization (100 scenarios): ~30 seconds.

---

## Stage Details

### S1: Crop Selection & Parameterization

**Input**: Crop name, planting date (MM/DD), optional parameter overrides
**Output**: `Crop` object
**Tool**: `select_crop`

```python
from aquacrop import Crop
crop = Crop('Maize', planting_date='05/01')
# Override parameters:
crop = Crop('Maize', planting_date='05/01', HI0=0.50, Tbase=10)
```

**Key parameters to consider overriding**:
- `Tbase` / `Tupp`: Base and upper temperature for GDD accumulation
- `HI0`: Reference harvest index (0-1)
- `WP`: Normalized water productivity (g/m2)
- `CCx`: Maximum canopy cover (0-1)
- `Emergence`, `Maturity`, `Senescence`: Phenological timing (GDD or days)
- `PlantPop`: Plant population per hectare

**Decision**: Use GDD variant (e.g., `MaizeGDD`) for regions where temperature variability is high. Use calendar-day variant (e.g., `Maize`) for regions with stable growing seasons.

**Milestone**: `crop.Tbase < crop.Tupp` and `crop.Emergence < crop.Maturity`

---

### S2: Soil Profile Setup

**Input**: Soil type name or custom layer definitions
**Output**: `Soil` object with hydraulic properties
**Tool**: `create_soil_profile`, `validate_soil_hydraulics`

```python
from aquacrop import Soil
# Built-in:
soil = Soil('SandyLoam')
# Custom:
soil = Soil('custom')
soil.add_layer(thickness=0.3, thWP=0.10, thFC=0.22, thS=0.41, Ksat=1200, penetrability=100)
soil.add_layer(thickness=0.9, thWP=0.15, thFC=0.31, thS=0.46, Ksat=500, penetrability=100)
# From texture:
soil = Soil('custom')
soil.add_layer_from_texture(thickness=0.3, Sand=55, Clay=15, OrgMat=2, penetrability=100)
```

**CRITICAL**: `thWP < thFC < thS` must hold for ALL layers. Violation causes assertion error.

**Built-in types** (with key properties):

| Type | thWP | thFC | thS | Ksat (mm/day) | CN |
|------|------|------|-----|---------|-----|
| Sand | 0.06 | 0.13 | 0.36 | 3000 | 46 |
| LoamySand | 0.08 | 0.16 | 0.38 | 2200 | 46 |
| SandyLoam | 0.10 | 0.22 | 0.41 | 1200 | 46 |
| Loam | 0.15 | 0.31 | 0.46 | 500 | 61 |
| SiltLoam | 0.13 | 0.33 | 0.46 | 575 | 61 |
| Silt | 0.09 | 0.33 | 0.43 | 500 | 61 |
| SandyClayLoam | 0.20 | 0.32 | 0.47 | 225 | 72 |
| ClayLoam | 0.23 | 0.39 | 0.50 | 125 | 72 |
| SiltClayLoam | 0.23 | 0.44 | 0.52 | 150 | 72 |
| SandyClay | 0.27 | 0.39 | 0.50 | 35 | 77 |
| SiltClay | 0.32 | 0.50 | 0.54 | 100 | 72 |
| Clay | 0.39 | 0.54 | 0.55 | 35 | 77 |

**Milestone**: `soil.nLayer >= 1` and `soil.profile` DataFrame has no NaN in hydraulic columns

---

### S3: Weather Data Preparation

**Input**: Daily weather data source (file, VIC output, or raw arrays)
**Output**: pandas DataFrame with columns: `MinTemp`, `MaxTemp`, `Precipitation`, `ReferenceET`, `Date`
**Tools**: `prepare_weather_df`, `compute_eto_penman_monteith`, `validate_weather_df`

```python
from aquacrop.utils import prepare_weather
# From AquaCrop-format text file (7 columns: Day Month Year MinTemp MaxTemp Precip ET0):
weather_df = prepare_weather('path/to/weather.txt')

# From VIC/CMFD/MSWX forcing (requires ET0 computation):
import pandas as pd
weather_df = pd.DataFrame({
    'MinTemp': tmin_array,     # deg C
    'MaxTemp': tmax_array,     # deg C
    'Precipitation': prcp_array, # mm/day
    'ReferenceET': et0_array,  # mm/day, MUST compute from Penman-Monteith
    'Date': pd.date_range(start='2000-01-01', periods=len(tmin_array), freq='D')
})
```

**CRITICAL**: `ReferenceET` is REQUIRED and must be > 0. AquaCrop clips it to minimum 0.1 mm/day internally. Unlike DSSAT which computes ET internally, AquaCrop expects pre-computed ET0 from the user.

**Unit conversion table (VIC to AquaCrop)**:

| Variable | VIC unit | AquaCrop unit | Conversion |
|----------|----------|---------------|-----------|
| Temperature | deg C | deg C | none |
| Precipitation | mm/timestep | mm/day | sum to daily |
| SW radiation | W/m2 | MJ/m2/day | multiply by 0.0864 (for ET0 computation) |
| Wind | m/s | m/s | none (used for ET0 computation) |

**Milestone**: All 5 columns present, no gaps in daily dates, `ReferenceET.min() > 0`

---

### S4: Initial Water Content

**Input**: Water content specification (property, numeric, or percentage)
**Output**: `InitialWaterContent` object
**Tool**: `create_initial_water_content`

```python
from aquacrop import InitialWaterContent
# At field capacity (simplest, recommended default):
iwc = InitialWaterContent(wc_type='Prop', method='Layer', depth_layer=[1], value=['FC'])
# At 70% of TAW:
iwc = InitialWaterContent(wc_type='Pct', method='Layer', depth_layer=[1], value=[70])
# Numeric (m3/m3) per layer:
iwc = InitialWaterContent(wc_type='Num', method='Layer', depth_layer=[1,2], value=[0.25, 0.30])
```

**CRITICAL**: For custom multi-layer soils, you MUST specify multi-layer IWC. If you use a single-layer IWC with a multi-layer soil, all layers default to FC silently (no warning).

**Milestone**: `iwc.wc_type` in valid set, layer count matches soil layers for custom soils

---

### S5: Irrigation Management

**Input**: Irrigation method and method-specific parameters
**Output**: `IrrigationManagement` object
**Tool**: `create_irrigation_management`, `optimize_deficit_irrigation`

```python
from aquacrop import IrrigationManagement
# Rainfed:
irr_rainfed = IrrigationManagement(irrigation_method=0)
# Soil moisture target (deficit irrigation):
irr_deficit = IrrigationManagement(irrigation_method=1, SMT=[70, 80, 80, 70])
# Net irrigation at 80% TAW:
irr_net = IrrigationManagement(irrigation_method=4, NetIrrSMT=80)
# Predefined schedule:
import pandas as pd
schedule = pd.DataFrame({
    'Date': pd.to_datetime(['2000/06/15', '2000/07/01', '2000/07/15']),
    'Depth': [25, 30, 25]
})
irr_schedule = IrrigationManagement(irrigation_method=3, Schedule=schedule)
```

**SMT values** for method=1 correspond to growth stages: [emergence-to-anthesis, anthesis-to-max-canopy, max-canopy-to-senescence, senescence-to-maturity]. Each value is the %TAW threshold below which irrigation is triggered.

**Milestone**: Method code valid, SMT values 0-100 if applicable

---

### S6: Field Management

**Input**: Mulch, bund, curve number settings
**Output**: `FieldMngt` object
**Tool**: `create_field_management`

```python
from aquacrop import FieldMngt
# Default (no management):
field = FieldMngt()
# With mulches:
field = FieldMngt(mulches=True, mulch_pct=50, f_mulch=0.5)
# With bunds (for paddy rice):
field = FieldMngt(bunds=True, z_bund=0.15, bund_water=0)  # z_bund in METERS
```

**CRITICAL**: `z_bund` is specified in **meters** but immediately converted to **mm** internally (multiplied by 1000). Do NOT pass mm values -- a 150mm bund should be entered as 0.15.

---

### S7: Model Assembly

**Input**: All component objects + simulation dates
**Output**: `AquaCropModel` instance
**Tool**: `assemble_model`, `validate_model_config`

```python
from aquacrop import AquaCropModel
model = AquaCropModel(
    sim_start_time='2000/05/01',    # YYYY/MM/DD with SLASHES
    sim_end_time='2000/12/31',
    weather_df=weather_df,
    soil=soil,
    crop=crop,
    initial_water_content=iwc,
    irrigation_management=irr,      # optional, default rainfed
    field_management=field,          # optional
    off_season=False,                # True to simulate fallow periods
)
```

**CRITICAL**: Date format MUST use slashes (`/`), NOT dashes (`-`). `'2000-05-01'` raises ValueError.

**Milestone**: Model instantiated without ValueError

---

### S8: Model Execution

**Input**: Assembled `AquaCropModel`
**Output**: Populated output DataFrames
**Tool**: `run_aquacrop`

```python
model.run_model(till_termination=True)  # Returns True when done
# Alternative: step-by-step
model.run_model(num_steps=30, initialize_model=True)
model.run_model(num_steps=30, initialize_model=False)  # Continue from last state
```

**Runtime**: < 1 second for single season. Pure Python, no external calls.

**Milestone**: `run_model()` returns `True`

---

### S9: Output Analysis

**Input**: Executed model
**Output**: DataFrames and CSV files with simulation results
**Tool**: `extract_results`, `compare_sim_obs`

```python
# Seasonal summary:
final_stats = model.get_simulation_results()
# Daily water flux:
water_flux = model.get_water_flux()
# Daily crop growth:
crop_growth = model.get_crop_growth()
# Daily soil water storage:
water_storage = model.get_water_storage()
```

**Key output columns to check**:
- `Dry yield (tonne/ha)` in final_stats: should be > 0 if crop reached maturity
- `Tr` in water_flux: actual transpiration, should be > 0 during growing season
- `canopy_cover` in crop_growth: should rise, plateau, then decline
- `biomass` in crop_growth: should increase monotonically until senescence

**Milestone**: Dry yield > 0 and physically reasonable for the crop

---

### S10: Water Productivity Analysis

**Input**: Output DataFrames from S9
**Output**: Water productivity metrics and scenario comparisons
**Tools**: `compute_water_productivity`, `compare_irrigation_scenarios`

```python
# Compute WP:
seasonal_et = water_flux.groupby('season_counter')[['Es', 'Tr']].sum()
seasonal_et['ET'] = seasonal_et['Es'] + seasonal_et['Tr']
yield_kg = final_stats['Dry yield (tonne/ha)'].values * 1000
et_mm = seasonal_et['ET'].values
cwp = yield_kg / et_mm   # kg/m3 (since 1 mm = 1 L/m2 = 0.001 m3/m2)

# Irrigation water use efficiency:
seasonal_irr = water_flux.groupby('season_counter')['IrrDay'].sum()
iwue = yield_kg / seasonal_irr.values  # kg/m3

# Water footprint:
wf = (et_mm * 10) / (yield_kg / 1000)  # m3/tonne
```

**Typical CWP ranges** (kg/m3):
- Maize: 1.5-2.5
- Wheat: 0.8-1.5
- Rice: 0.6-1.1
- Soybean: 0.5-0.8

**Milestone**: CWP computed and within expected range for crop type

---

## Coverage Summary

| Layer | Coverage |
|-------|---------|
| Validated Tools (Layer 1) | 17 tools across 10 stages |
| Skill Documents (Layer 2) | 10 docs, all 7 sections each |
| Diagnostic Triplets (Layer 3) | 15 triplets across 9 failure domains |
