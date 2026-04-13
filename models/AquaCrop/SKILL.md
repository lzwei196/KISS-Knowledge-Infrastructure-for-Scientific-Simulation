> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)

> **HWSD soil lookup:** Use `from ki_tools_common.soil_utils import lookup_hwsd` to get sand/silt/clay/OC/pH for any lat/lon. Returns texture class and Saxton-Rawls hydraulic properties.

> **CMFD direct reader available:** Use `from ki_tools_common.netcdf_utils import load_cmfd_daily_all` to read CMFD 3-hourly data directly. Returns daily precip (mm), temp (°C with Tmin/Tmax), radiation (W/m²), wind, humidity. Handles subdirectory search (Prec/, Temp/, etc.) and unit conversions automatically.

> **HWSD soil lookup:** Use `from ki_tools_common.soil_utils import lookup_hwsd` to get sand/silt/clay/OC/pH for any lat/lon. Returns texture class and Saxton-Rawls hydraulic properties.
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
AquaCrop forcing tools are in `tools/s3_weather_prep/` in this KI:
- `tools/s3_weather_prep/prepare_weather_df.py` — Creates weather DataFrame with AquaCrop columns (MinTemp, MaxTemp, Precipitation, ReferenceET, Date)
- `tools/s3_weather_prep/compute_eto_penman_monteith.py` — Computes reference ET (ET0) via Penman-Monteith
- `tools/s3_weather_prep/validate_weather_df.py` — Validates weather DataFrame format, ranges, and continuity

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.

---

# AquaCrop-OSPy Knowledge Infrastructure

**Package**: `aquacrop-ospy-knowledge` v1.0.0
**Target Model**: AquaCrop-OSPy v3.0.12 (FAO AquaCrop v7.1 Python implementation)
**Domain**: Crop-water productivity modeling and deficit irrigation optimization
**Install**: `pip install aquacrop` (requires numpy>=1.22, pandas>=2.0, tqdm>=4.65)

---

## What This Enables

An AI agent can autonomously run AquaCrop-OSPy simulations for any supported crop and location by following this infrastructure. The unique strength of AquaCrop over DSSAT or WOFOST is **water productivity analysis**: quantifying crop yield per unit of water consumed, and optimizing deficit irrigation strategies to maximize yield under limited water supply.

AquaCrop-OSPy is a **pure-Python** model -- no compilation, no config files, no file I/O during execution. All inputs are Python objects, the model runs in-memory, and outputs are pandas DataFrames. This makes it the fastest crop model to set up and the easiest to couple with other Python-based tools.

---

## Pipeline Overview (10 Stages)

| Stage | Name | Skill Document | Key Tools | Depends On |
|-------|------|---------------|-----------|------------|
| S1 | Crop Selection | `docs/s1_crop_selection_skill.md` | `select_crop`, `validate_crop_params` | -- |
| S2 | Soil Profile | `docs/s2_soil_profile_skill.md` | `create_soil_profile`, `validate_soil_hydraulics` | -- |
| S3 | Weather Preparation | `docs/s3_weather_prep_skill.md` | `prepare_weather_df`, `compute_eto_penman_monteith`, `validate_weather_df` | -- |
| S4 | Initial Water Content | `docs/s4_initial_conditions_skill.md` | `create_initial_water_content` | S2 |
| S5 | Irrigation Management | `docs/s5_irrigation_skill.md` | `create_irrigation_management`, `optimize_deficit_irrigation` | -- |
| S6 | Field Management | `docs/s6_field_management_skill.md` | `create_field_management` | -- |
| S7 | Model Assembly | `docs/s7_model_assembly_skill.md` | `assemble_model`, `validate_model_config` | S1-S6 |
| S8 | Execution | `docs/s8_execution_skill.md` | `run_aquacrop` | S7 |
| S9 | Output Analysis | `docs/s9_output_analysis_skill.md` | `extract_results`, `compare_sim_obs` | S8 |
| S10 | Water Productivity | `docs/s10_water_productivity_skill.md` | `compute_water_productivity`, `compare_irrigation_scenarios` | S9 |

Stages S1, S2, S3, S5, S6 can run in **parallel** (they are independent). S4 depends on S2. S7 depends on all of S1-S6.

---

## Critical Domain Knowledge

### 1. Weather DataFrame Format (S3) -- Most Common Error Source

AquaCrop-OSPy requires a pandas DataFrame with **exactly** these columns:

| Column | Type | Unit | Notes |
|--------|------|------|-------|
| `MinTemp` | float | deg C | Daily minimum temperature |
| `MaxTemp` | float | deg C | Daily maximum temperature |
| `Precipitation` | float | mm/day | Daily total precipitation |
| `ReferenceET` | float | mm/day | FAO-56 reference evapotranspiration. **MUST be > 0** (clipped to 0.1 internally) |
| `Date` | pd.Timestamp | -- | Datetime index for each day |

**If ReferenceET is missing from your data source, you MUST compute it** using FAO Penman-Monteith.
Use `tools/s3_weather_prep/compute_eto_penman_monteith.py` — it takes solar radiation (MJ/m²/day), wind (m/s), temp, and lat/elevation. **Do NOT use simplified Hargreaves with a fixed Ra** — this produces wildly wrong ET0 that causes AquaCrop maize yields to converge to ~14 t/ha (potential production, no water stress) or wheat yields to drop to near zero. The full Penman-Monteith needs radiation + wind + humidity from `ki_tools_common.load_forcing`.

```python
from tools.s3_weather_prep.compute_eto_penman_monteith import compute_et0_fao56
et0 = compute_et0_fao56(
    tmin=data['temp_min_c'], tmax=data['temp_max_c'],
    solar_rad=data['srad_wm2'] * 0.0864,  # W/m² → MJ/m²/day
    wind=data['wind_ms'], lat=32.9, elevation=30,
    doy=np.array([d.astype('datetime64[D]').astype(int) % 365 + 1 for d in data['dates']]),
)
```

AquaCrop will NOT run without ET0. This is the #1 difference from DSSAT (which computes ET internally).

### 2. Date Format (S7) -- Silent Failure

Simulation dates must use **slash separators**: `'YYYY/MM/DD'`. Using dashes (`'YYYY-MM-DD'`) raises `ValueError`. This is checked at model construction time.

### 3. Soil Hydraulic Ordering (S2) -- Fatal Constraint

For all soil layers: **thWP < thFC < thS** must hold. Violation causes assertion error. When using `add_layer_from_texture()`, the Saxton-Rawls pedotransfer function computes these automatically, but manual layers can easily violate this if values are swapped.

### 4. Built-in Soil Types (S2)

`Clay`, `ClayLoam`, `Default`, `Loam`, `LoamySand`, `Sand`, `SandyClay`, `SandyClayLoam`, `SandyLoam`, `Silt`, `SiltClay`, `SiltClayLoam`, `SiltLoam`, `Paddy`, `ac_TunisLocal`, `custom`

### 5. Built-in Crop Types (S1)

Calendar-day crops: `Barley`, `Cotton`, `Default`, `DryBean`, `Maize`, `PaddyRice`, `Potato`, `Quinoa`, `Sorghum`, `Soybean`, `SugarBeet`, `SugarCane`, `Sunflower`, `Tomato`, `Wheat`, `Tef`, `Cassava`, `localpaddy`

GDD crops: `BarleyGDD`, `CottonGDD`, `DryBeanGDD`, `MaizeGDD`, `PaddyRiceGDD`, `PotatoGDD`, `PotatoLocalGDD`, `SorghumGDD`, `SoybeanGDD`, `SugarBeetGDD`, `SugarBeetGDD_UK`, `SunflowerGDD`, `TomatoGDD`, `WheatGDD`, `WheatGDD_1dec`, `HydWheatGDD`, `WheatLongGDD`, `AlfalfaGDD`, `MaizeChampionGDD`

GDD variants are preferred because they adapt phenology to local temperature. Calendar-day variants use fixed development timing.

### Validated Results (2026-04-11, 3×3 matrix)

| Site | Crop | Default yield | With fertility adj | Obs (SPAM) | WP used |
|------|------|---------------|-------------------|------------|---------|
| Bengbu | Maize | 13,923 (potential) | **5,376** | 5,500 | WP=15, CCx=0.80 |
| Bengbu | Wheat | 1,644 | needs tuning | 5,750 | default (too low) |
| Harbin | Maize | 13,585 (potential) | ~7,000 | 6,000-8,000 | WP=20, CCx=0.85 |
| São Paulo | Soybean | 4,771 | — | 3,250 | default (acceptable) |

### CRITICAL: Soil Fertility Stress (AquaCrop's #1 trap for humid regions)

AquaCrop-OSPy does **NOT model nitrogen limitation**. In humid regions (precip > ET0), water stress never activates and yields converge to potential (~14 t/ha for maize). This is NOT a bug — it's by design.

**To simulate realistic rainfed yields under sub-optimal fertility:**
```python
crop = Crop('Maize', planting_date='06/10')
crop.WP = 15.0    # Default 33.7 → reduce to 15-20 for developing-world maize
crop.CCx = 0.80   # Default 0.96 → reduce for sub-optimal stand density
```

**WP (Water Productivity) calibration guide:**

| WP (g/m²) | CCx | Expected yield | Represents |
|------------|-----|----------------|------------|
| 33.7 (default) | 0.96 | ~14,000 kg/ha | Potential (US irrigated, optimal N) |
| 25.0 | 0.85 | ~9,000 kg/ha | High-input commercial (NE China, Brazil) |
| 20.0 | 0.80 | ~7,000 kg/ha | Moderate-input (Harbin rainfed) |
| 15.0 | 0.80 | ~5,400 kg/ha | Low-input (Bengbu traditional) |
| 12.0 | 0.75 | ~4,000 kg/ha | Subsistence (Sub-Saharan Africa) |

For wheat: default WP=15 is already low — the issue is different (phenology tuning needed for Chinese winter wheat varieties).

**Rule**: If your site has P > ET0 during the growing season (monsoon Asia, humid tropics), you MUST reduce WP/CCx or yields will be unrealistically high. AquaCrop only limits growth via water — there is no N/P module.

### 6. Irrigation Methods (S5)

| Method | Code | Key Parameter | Use Case |
|--------|------|--------------|----------|
| Rainfed | 0 | -- | No irrigation baseline |
| Soil Moisture Target | 1 | `SMT=[s1,s2,s3,s4]` (% TAW) | Deficit irrigation optimization |
| Fixed Interval | 2 | `IrrInterval` (days) | Simple scheduling |
| Predefined Schedule | 3 | `Schedule` (DataFrame: Date, Depth) | Known historical irrigation |
| Net Irrigation | 4 | `NetIrrSMT` (% TAW) | Full/supplemental irrigation |
| Constant Depth | 5 | `depth` (mm/day) | Continuous drip/flood |

### 7. Output DataFrames (S9)

**`get_simulation_results()`** -- seasonal summary:
`Season`, `crop Type`, `Harvest Date (YYYY/MM/DD)`, `Harvest Date (Step)`, `Dry yield (tonne/ha)`, `Fresh yield (tonne/ha)`, `Yield potential (tonne/ha)`, `Seasonal irrigation (mm)`

**`get_water_flux()`** -- daily water balance:
`time_step_counter`, `season_counter`, `dap`, `Wr`, `z_gw`, `surface_storage`, `IrrDay`, `Infl`, `Runoff`, `DeepPerc`, `CR`, `GwIn`, `Es`, `EsPot`, `Tr`, `TrPot`

**`get_crop_growth()`** -- daily crop state:
`time_step_counter`, `season_counter`, `dap`, `gdd`, `gdd_cum`, `z_root`, `canopy_cover`, `canopy_cover_ns`, `biomass`, `biomass_ns`, `harvest_index`, `harvest_index_adj`, `DryYield`, `FreshYield`, `YieldPot`

**`get_water_storage()`** -- daily soil water per compartment:
`time_step_counter`, `growing_season`, `dap`, `th1`, `th2`, ..., `thN`

---

## Tools Reference

| Stage | Tool ID | Script Path | Purpose |
|-------|---------|------------|---------|
| S1 | `select_crop` | `tools/s1_crop_selection/select_crop.py` | Create Crop object from built-in or custom |
| S1 | `validate_crop_params` | `tools/s1_crop_selection/validate_crop_params.py` | Check GDD, stress, HI consistency |
| S2 | `create_soil_profile` | `tools/s2_soil_profile/create_soil_profile.py` | Create Soil from type or custom layers |
| S2 | `validate_soil_hydraulics` | `tools/s2_soil_profile/validate_soil_hydraulics.py` | Check thWP < thFC < thS |
| S3 | `prepare_weather_df` | `tools/s3_weather_prep/prepare_weather_df.py` | Convert source data to AquaCrop DataFrame |
| S3 | `compute_eto_penman_monteith` | `tools/s3_weather_prep/compute_eto_penman_monteith.py` | Compute ET0 from met variables |
| S3 | `validate_weather_df` | `tools/s3_weather_prep/validate_weather_df.py` | Validate column names, ranges, completeness |
| S4 | `create_initial_water_content` | `tools/s4_initial_conditions/create_initial_water_content.py` | Set initial soil water |
| S5 | `create_irrigation_management` | `tools/s5_irrigation/create_irrigation_management.py` | Define irrigation strategy |
| S5 | `optimize_deficit_irrigation` | `tools/s5_irrigation/optimize_deficit_irrigation.py` | SMT sweep for yield-water tradeoff |
| S6 | `create_field_management` | `tools/s6_field_management/create_field_management.py` | Mulches, bunds, CN adjustment |
| S6 | `apply_cama_flood` | `tools/s6_field_management/apply_cama_flood.py` | CaMa-Flood flddph/fldfrc to AquaCrop GroundWater for waterlogging stress |
| S7 | `assemble_model` | `tools/s7_model_assembly/assemble_model.py` | Combine all into AquaCropModel |
| S7 | `validate_model_config` | `tools/s7_model_assembly/validate_model_config.py` | Pre-flight consistency checks |
| S8 | `run_aquacrop` | `tools/s8_execution/run_aquacrop.py` | Execute simulation |
| S9 | `extract_results` | `tools/s9_output_analysis/extract_results.py` | Export outputs to CSV |
| S9 | `compare_sim_obs` | `tools/s9_output_analysis/compare_sim_obs.py` | Compute RMSE, d-index, bias |
| S10 | `compute_water_productivity` | `tools/s10_water_productivity/compute_water_productivity.py` | CWP, IWUE, water footprint |
| S10 | `compare_irrigation_scenarios` | `tools/s10_water_productivity/compare_irrigation_scenarios.py` | Multi-scenario comparison |

---

## Error Handling

See `diagnostics/triplets.yaml` for 18 diagnostic triplets covering:
- Missing/wrong ET0 (dt_001) -- most common error
- Wrong GDD base temperature (dt_002) -- silent error, wrong phenology
- Soil hydraulic ordering violation (dt_003) -- fatal assertion
- Initial water content too dry (dt_004) -- crop death
- Wrong planting date season (dt_005) -- zero yield
- API version column name changes (dt_006)
- Weather DataFrame column name mismatch (dt_007) -- ValueError
- Silent crop death from waterlogging (dt_008)
- Date format with dashes not slashes (dt_009) -- ValueError
- Off-season simulation disabled (dt_010)
- Custom soil missing add_layer (dt_011) -- assertion failure
- IWC layer count mismatch (dt_012) -- silent default to FC
- Schedule DataFrame format error (dt_013)
- Yield is zero but model ran (dt_014) -- silent error
- Bund height in wrong units (dt_015) -- silent error

---

## Model Couplings

See `docs/model_couplings.yaml` for data flows between AquaCrop-OSPy and:
- **VIC**: Weather forcing (7 vars) -> AquaCrop DataFrame (4 vars + ET0)
- **VIC**: Soil moisture -> InitialWaterContent
- **HWSD**: Sand/Clay/OrgMat -> `add_layer_from_texture()`
- **CaMa-Flood**: Flood depth/duration -> AquaCrop GroundWater object for mechanistic waterlogging stress — **IMPLEMENTED** via `apply_cama_flood.py` (s6_field_management). Validation: Bengbu maize 1985: 14.18 t/ha (no flood) -> 4.28 t/ha (with flood, -69.8%). 177 flood days from CaMa-Flood.
  ```python
  from apply_cama_flood import build_groundwater_from_cama
  gw, df = build_groundwater_from_cama("model/cmf_v420_pkg/out/<run>", lat, lon, start, end)
  model = AquaCropModel(..., groundwater=gw)
  ```
- **DSSAT/WOFOST**: Triple ensemble yield comparison
- **Water management**: Irrigation optimization -> policy recommendations

---

## Quick Start Example

```python
from aquacrop import AquaCropModel, Soil, Crop, InitialWaterContent, IrrigationManagement
from aquacrop.utils import prepare_weather, get_filepath

# S3: Weather
weather_data = get_filepath('champion_climate.txt')
weather_df = prepare_weather(weather_data)

# S2: Soil
soil = Soil('SandyLoam')

# S1: Crop
crop = Crop('Maize', planting_date='05/01')

# S4: Initial conditions
iwc = InitialWaterContent(wc_type='Prop', value=['FC'])

# S5: Irrigation (deficit at 70% TAW)
irr = IrrigationManagement(irrigation_method=1, SMT=[70]*4)

# S7: Assemble
model = AquaCropModel(
    sim_start_time='1982/05/01',
    sim_end_time='1983/05/01',
    weather_df=weather_df,
    soil=soil, crop=crop,
    initial_water_content=iwc,
    irrigation_management=irr,
)

# S8: Run
model.run_model(till_termination=True)

# S9: Results
final = model.get_simulation_results()
flux = model.get_water_flux()
growth = model.get_crop_growth()

# S10: Water productivity
seasonal_et = flux.groupby('season_counter')[['Es','Tr']].sum()
seasonal_et['ET'] = seasonal_et['Es'] + seasonal_et['Tr']
wp = final['Dry yield (tonne/ha)'].values * 1000 / seasonal_et['ET'].values  # kg/m3
```

---

*This knowledge infrastructure was created using the Knowledge Dissection Toolkit developed by the Jianyun Zhang Research Group, Hohai University.*

---

## Crop Calendar Reference (China)

| Region | Latitude | Winter Wheat | Summer Maize | Rice |
|--------|----------|-------------|-------------|------|
| Northeast | >40°N | — | May-Sep | — |
| North China | 35-40°N | Oct-Jun | Jun-Sep | — |
| Huang-Huai | 32-35°N | Oct-Jun | Jun-Oct | — |
| Yangtze | 28-32°N | Nov-May | — | Apr-Oct |
| South | <28°N | — | — | Mar-Jul, Jul-Nov |

**Data sources on server:**
- GGCMI Crop Calendar: `/home/server/Crop_model_dataset/GGCMI_phase3_crop_calendar/`
- China Phenology GeoTIFF: `/home/server/Crop_model_dataset/8313530/`
- SPAM crop distribution: `/home/server/Crop_model_dataset/dataverse_files/`
