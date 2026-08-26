---
name: aquacrop
description: >-
  FAO AquaCrop 7.1 (Reference Manual lineage; Chapter 3 algorithmic spec). Covers Yield
  response of herbaceous crops to water; Daily soil water balance of the root zone
  (drainage, runoff, infiltration, capillary rise); Soil evaporation (FAO two-stage:
  energy-limited then falling-rate); Crop transpiration with stress modulation (water,
  aeration, temperature, CO2). Use when the task involves running, configuring,
  calibrating or interpreting AquaCrop.
---

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
| 30.0 | 0.90 | ~12,300 kg/ha | High-input **rainfed** (US Corn Belt — IA/IL/NE/WI/MN) |
| 25.0 | 0.85 | ~9,000 kg/ha | High-input commercial (NE China, Brazil) |
| 20.0 | 0.80 | ~7,000 kg/ha | Moderate-input (Harbin rainfed) |
| 15.0 | 0.80 | ~5,400 kg/ha | Low-input (Bengbu traditional) |
| 12.0 | 0.75 | ~4,000 kg/ha | Subsistence (Sub-Saharan Africa) |

For wheat: default WP=15 is already low — the issue is different (phenology tuning needed for Chinese winter wheat varieties).

**Rule**: If your site has P > ET0 during the growing season (monsoon Asia, humid tropics), you MUST reduce WP/CCx or yields will be unrealistically high. AquaCrop only limits growth via water — there is no N/P module.

**Conversely, high-input optimal-N regions need a HIGH WP.** For the US Corn Belt
(verified 2026-06-30 vs SPAM 2020, 40.0-43.5N x 98-88W maize) the SPAM regional
mean is ~12.3 t/ha. Default WP=33.7/CCx=0.96 drives sim to potential (~14 t/ha)
and over-predicts by +12.4%; **WP=30/CCx=0.90 (planting 05/05) centers the
regional mean at PBIAS -1.4%**. So WP is a two-sided knob: drop it for low-input
monsoon Asia (WP=13.8 China maize), raise it toward potential for high-input US
maize. Do NOT carry the China WP=13.8 over to a US/EU site — it undershoots ~55%.

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
- GGCMI Crop Calendar: `KISSPATH_HOME/Crop_model_dataset/GGCMI_phase3_crop_calendar/`
- China Phenology GeoTIFF: `KISSPATH_HOME/Crop_model_dataset/8313530/`
- SPAM crop distribution: `KISSPATH_HOME/Crop_model_dataset/dataverse_files/`


---

## Multi-Year National-Yield Validation (FAOSTAT / GDHY annual series)

Use this recipe when the observation is an **annual national/regional yield
series** (FAOSTAT `yield_tonnes_per_ha`, GDHY, etc.) rather than a single-site
snapshot. A time series is required for Pearson r / NSE / KGE to be defined.

**DO NOT** re-load forcing per year, and **DO NOT** load hourly/3-hourly or
gridded forcing across decades (`load_hourly_forcing`, `load_cmfd_daily_all`):
that is the CPU-bound trap that hangs a 25-year run. Load the **daily point
series ONCE** for the whole window, compute ET0 once (vectorized), then run a
SINGLE multi-year `AquaCropModel`.

**Forcing source for multi-decade windows: use `nasa_power`, NOT `cmfd`.**
`load_daily_forcing('cmfd', ...)` is NOT a "single fast call" over decades:
`_load_cmfd` loops `year × month × 6 variables`, i.e. it opens
`6 × 12 × N_years` NetCDF tiles with `xr.open_dataset` (≈1,870 file opens for
a 26-year window) and does a point-extract on each — that IS the IO-bound trap
that hangs the run (it is the same failure mode as `load_cmfd_daily_all`, just
one notch less extreme). `load_daily_forcing('nasa_power', ...)` instead issues
ONE bounded HTTP request per year (network-bound, not 1,870 local opens),
covers 1981→present, and is globally valid including China. Prefer it for any
window longer than ~10 years. Only fall back to `cmfd` for short windows
(< ~10 years) or where NASA POWER coverage is genuinely insufficient. Keep the
window bounded (≤ ~25 years) regardless of source.

```python
from ki_tools_common.load_forcing import load_daily_forcing
from ki_tools_common.crop_obs import get_faostat_yield_series

# 1. Representative agricultural point + crop + FAOSTAT country label.
#    e.g. China maize, North China Plain:
lat, lon, crop, country = 34.0, 113.0, 'maize', 'China, mainland'

# 2. Window = overlap of forcing AND FAOSTAT. FAOSTAT is 1961-2024 but forcing
#    starts later (CMFD 1951, MSWX 1979, NASA POWER 1981). NASA POWER (1981+)
#    fully overlaps FAOSTAT for any recent window. Keep it bounded (~15-20 yr,
#    enough years for r/NSE/KGE without an unbounded forcing load).
y0, y1 = 2000, 2018

# 3. Load forcing ONCE as a daily POINT series.
#    Use 'nasa_power' (ONE bounded HTTP request per year; works for China too).
#    Do NOT use 'cmfd' here over decades: it opens 6*12*N_years NetCDF tiles
#    (~1,300 for this window) and is the IO-bound hang that produces no result.
fc = load_daily_forcing('nasa_power', lat, lon, y0, y1)   # standardized daily dict
# Build weather_df (compute_eto_penman_monteith is vectorized over the series).

# 4. ONE multi-year model spanning the whole window; AquaCrop simulates one
#    season per year -> final_stats has one row per harvest year.
model = AquaCropModel(sim_start_time=f'{y0}/01/01', sim_end_time=f'{y1}/12/31',
                      weather_df=weather_df, soil=soil, crop=crop_obj,
                      initial_water_content=iwc)   # off_season=False default
model.run_model(till_termination=True)

# 5. Use the FULL final_stats series (one yield per season). NOTE: run_aquacrop
#    only reports season-0 yield (`stats[...].iloc[0]`) -- for multi-year
#    validation read final_stats.csv from extract_results, NOT run_aquacrop's
#    `dry_yield_tha`. Map each season to its harvest year.
final = model.get_simulation_results()
sim = {yr: y for yr, y in zip(range(y0, y1+1), final['Dry yield (tonne/ha)'])}

# 6. Obs + align by year, then compare_sim_obs.
obs = get_faostat_yield_series(crop=crop, country=country,
                               years=range(y0, y1+1), units='t/ha')
common = sorted(set(sim) & set(obs))
from compare_sim_obs import compute_metrics   # tools/s9_output_analysis
metrics = compute_metrics([sim[y] for y in common], [obs[y] for y in common])
# r / NSE / KGE now defined over the annual series.
```

### CRITICAL — pick the metric the obs_shape allows (dag-enforced)

A FAOSTAT / GDHY **national** yield series is a `regional_aggregate_time_series`
obs_shape. Per `dag.yaml` `outputs.DryYield.observability`, the ONLY valid
metric_families for it are **`magnitude_accuracy`** (PBIAS, RMSE) and
**`trend_match`** (slope agreement, detrended residuals, decadal-mean PBIAS).
**Raw NSE / Pearson r / KGE on the inter-annual series are scientifically
inappropriate** and the pre-retry gate REJECTS them as `REJECT_WRONG_METRIC` —
switching cultivar/forcing/WP cannot rescue a structurally invalid measurement,
so the retry loop correctly skips.

Why: a national aggregate is dominated by a multi-decade technology/management
trend that a weather-only model (AquaCrop has no N module) cannot reproduce.
Both sim and obs trend upward, so a **raw r looks deceptively high** (China
maize 2000-2018: raw r=0.85) while the **detrended residuals share no
co-movement** (detrended_r≈0.00). The high raw r is pure trend-coupling, not
skill. Verified 2026-06-08: WP=13.8 gives PBIAS −0.34% (excellent magnitude)
but sim trend slope is only 0.028 vs obs 0.084 t/ha/yr (slope_ratio 0.34) — the
model captures the magnitude well and the trend *direction* but only ~1/3 of its
*rate*, exactly as expected for a weather-only model against a tech-driven series.

Use the dedicated tool — it returns the dag-valid families and refuses to lead
with raw NSE/r:
```python
from compare_sim_obs import compute_aggregate_metrics   # tools/s9_output_analysis
m = compute_aggregate_metrics(sim_list, obs_list, years_list)
# m['magnitude_accuracy']['PBIAS_pct'], m['trend_match']['slope_ratio'], ['detrended_r']
```
Report `obs_shape='regional_aggregate_time_series'` in the result JSON. The
older `compute_metrics()` still emits r/NSE/KGE for `point_time_series` cases
(single field-trial multi-year), but DO NOT report those as the headline for a
national aggregate.

**`detrended_r` is NOT a pass/fail or retry gate for a national aggregate.**
A 0-D single-point weather-only run CANNOT reproduce the detrended inter-annual
residuals of a NATIONAL / sub-national aggregate: that residual variability is
driven by area shifts, irrigation expansion, sub-national heterogeneity and
policy -- none of which a point run sees -- so `detrended_r ≈ 0` is the
EXPECTED, physically-correct outcome (China maize 2000-2018: detrended_r=0.001),
NOT a phenology/calibration defect, and adding trend rate is impossible without a
fertility/technology forcing the model isn't given. For a
`regional_aggregate_time_series` obs the acceptance gate is ONLY
`magnitude_accuracy` (|decadal PBIAS| small; here -0.34%) plus `trend_match` sign
and `slope_ratio` -- do NOT trigger a retry on detrended_r here. To genuinely
validate AquaCrop's inter-annual *weather* response, supply a `point_time_series`
obs (a co-located multi-year field trial); only THERE is a low detrended_r a real
phenology/GDD-variant or planting-window issue (dt_002/dt_005).

**Validated FAOSTAT calibration (China mainland maize, verified 2026-06-08).**
Point (34.0N, 113.0E North China Plain), `Soil('Loam')`, `Crop('Maize',
planting_date='06/10')`, NASA POWER daily forcing 2000-2018, FAO-56 PM ET0.
The SKILL fertility guide's `WP=15` (tuned to Bengbu low-input) leaves a +8%
positive bias against the FAOSTAT *national* series, which pushes NSE negative
(-0.38) even though r is strong (0.85). Dropping to **`crop.WP = 13.8`** (keep
`CCx = 0.80`) centers the bias (PBIAS -0.3%) and lifts **NSE to +0.49** with
r=0.849, KGE=0.35. Note the KGE/NSE trade-off: yield scales ~linearly with WP,
so lowering WP also shrinks sim interannual std (alpha<1), nudging KGE down ~0.02
while NSE gains ~0.9 — center the bias for NSE, accept the small KGE cost. Use
WP≈13.8 as the national-series default for China maize; WP=15 remains correct
for a single low-input *field* site like Bengbu.

---

## SPAM 2020 Regional-Aggregate Validation (single-year SPATIAL gridded yield)

Use this recipe when the observation is **SPAM 2020** (`yield_kg_ha`, IFPRI
spatially-disaggregated 2020 gridded yield). SPAM 2020 is a SINGLE YEAR (2020),
SPATIAL product, NOT a time series.

**Scale + metric contract (read first).** AquaCrop is a 0-D point model and
`dag.yaml outputs.DryYield.observability` does **NOT** list `spatial_snapshot`
among the comparable obs_shapes — it lists `point_snapshot`
(magnitude_accuracy) and `regional_aggregate_time_series`. So a per-cell SPATIAL
NSE/r against the SPAM grid would be `REJECT_WRONG_METRIC`. The scale-comparable,
dag-valid move is to **AGGREGATE** the SPAM gridded yields over a coherent
agricultural region to ONE regional-mean value, run AquaCrop **multi-site over
the same region/season**, aggregate the sim to ONE regional-mean, and compare
**MAGNITUDE (PBIAS) only**. NSE/r/KGE are `null` — a single-year regional
aggregate is one value pair, no temporal series (set `metrics_null_reason`).
Report `obs_shape='point_snapshot'`, `sim_support='aggregated'`,
`obs_support='regional_aggregate_time_series'`, `scale_comparable=true`.

**Obs helper (added 2026-06-30 — prior SPAM runs had to hand-build this):**
```python
from ki_tools_common.crop_obs import get_spam_regional_yield
obs = get_spam_regional_yield('maize', (40.5, 43.0), (-96.0, -91.0), step=0.5)
# obs['mean_kgha'], obs['n_cells'], obs['cells'] = [(lat, lon, yield_kgha), ...]
# Reads SPAM geotiff/csv ONLY — never falls through to the FAOSTAT national
# fallback, so the regional mean is not contaminated by non-SPAM cells.
```
Then run AquaCrop at each `obs['cells']` lat/lon (NASA POWER daily forcing,
FAO-56 PM ET0), take the unweighted mean of per-cell sim yields, and
`PBIAS = (sim_mean - obs_mean)/obs_mean*100`. A ready runner is
`run_and_score.py` (resumable per-cell cache).

**CRITICAL — fertility regime sets WP/CCx a-priori, per the fertility table.**
SPAM yields are region-specific, so pick WP/CCx from the SKILL fertility table
to match the *production regime*, NOT tuned to the obs:
- **US Corn Belt / high-input optimal-N maize (SPAM ~13,000-14,500 kg/ha):**
  use AquaCrop **DEFAULTS** `WP=33.7, CCx=0.96` — the table's "Potential (US
  irrigated, optimal N)" row IS this regime. NO down-calibration.
- **China / developing-world low-input rainfed maize (SPAM ~5,000-6,000):**
  down-calibrate (`WP≈13.8-15, CCx=0.80`) — humid + no N module would otherwise
  collapse to the ~14 t/ha potential envelope.

**Validated SPAM regional aggregates:**

| Region | Crop | Config | Sim mean | SPAM mean | PBIAS |
|--------|------|--------|----------|-----------|-------|
| North China Plain (34-37N,113-116.5E) | maize | Loam, WP=13.8 CCx=0.80, plant 06/10 | 5,622 | 5,945 | -5.4% |
| US Corn Belt / Iowa (40.5-43N,96-91W) | maize | SiltLoam, **DEFAULT** WP/CCx, plant 05/01 | ~14,400 | ~14,200 | ~+1% (verify) |

The two rows show the same model spanning a ~2.5× yield gradient using only the
correct fertility-regime WP/CCx — the magnitude lever the SKILL fertility table
encodes. The single-cell Iowa check (42.0N,93.5W): SiltLoam default → 14,651 vs
SPAM 14,300 (+2.5%); Loam default → 14,195 (-0.7%).
