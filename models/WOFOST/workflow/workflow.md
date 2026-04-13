# WOFOST/PCSE Simulation Workflow

## Pipeline Overview

```
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ S1: Crop Params  │   │ S2: Soil Params  │   │ S3: Weather Prep │   │ S4: AgroMgmt     │
│ (YAML/Provider)  │   │ (HWSD→bucket)    │   │ (CSV/NASA/VIC)   │   │ (YAML calendar)  │
└────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘
         │                      │                       │                      │
         └──────────────────────┼───────────────────────┼──────────────────────┘
                                │                       │
                      ┌─────────▼───────────────────────▼─────────┐
                      │          S5: Engine Configuration           │
                      │   ParameterProvider + Engine class select   │
                      └──────────────────┬─────────────────────────┘
                                         │
                      ┌──────────────────▼─────────────────────────┐
                      │          S6: Simulation Execution           │
                      │      engine.run_till_terminate()            │
                      └──────────────────┬─────────────────────────┘
                                         │
                      ┌──────────────────▼─────────────────────────┐
                      │          S7: Output Parsing                 │
                      │   get_output() → DataFrame → CSV            │
                      └──────────────────┬─────────────────────────┘
                                         │
                      ┌──────────────────▼─────────────────────────┐
                      │    S8: Yield Analysis & Ensemble            │
                      │  Spatial maps, DSSAT comparison, stats      │
                      └─────────────────────────────────────────────┘
```

## Dependencies

| Stage | Depends On | Can Parallelize With |
|-------|-----------|---------------------|
| S1: Crop Params | none | S2, S3, S4 |
| S2: Soil Params | none | S1, S3, S4 |
| S3: Weather Prep | none | S1, S2, S4 |
| S4: AgroMgmt | S1 (crop_name/variety must match) | S2, S3 |
| S5: Engine Config | S1, S2, S3, S4 | none |
| S6: Execution | S5 | none |
| S7: Output Parsing | S6 | none |
| S8: Yield Analysis | S7 | none |

## Stage Details

### S1: Crop Parameter Configuration

**Purpose**: Load crop growth parameters that define phenology, photosynthesis, partitioning, and leaf dynamics.

**Skill document**: `docs/s1_crop_params_skill.md`

**Tools**:
- `load_crop_parameters` — Load YAML crop parameters via YAMLCropDataProvider
- `validate_crop_params` — Verify parameter ranges and table monotonicity

**Key parameters**:
| Parameter | Description | Typical Range | Unit |
|-----------|-------------|---------------|------|
| TSUM1 | Thermal time emergence → anthesis | 500-1500 | C.d |
| TSUM2 | Thermal time anthesis → maturity | 500-1500 | C.d |
| TDWI | Initial total dry weight | 20-200 | kg/ha |
| SPAN | Max leaf life at 35C | 20-50 | d |
| TBASE | Base temperature for development | 0-10 | C |
| VERNSAT | Vernalization saturation (winter crops) | 30-70 | d |
| AMAXTB | Max CO2 assimilation rate table | varies | kg/ha/hr |

**Milestone**: `m1_crop_yaml_loaded` — YAMLCropDataProvider loads without exception

---

### S2: Soil Parameter Setup

**Purpose**: Define soil hydraulic properties for the WOFOST bucket water balance.

**Skill document**: `docs/s2_soil_params_skill.md`

**Tools**:
- `convert_hwsd_to_pcse_soil` — HWSD raster/MDB → WOFOST soil parameters
- `validate_soil_params` — Check SMW < SMFCF < SM0, K0 > 0

**Key parameters**:
| Parameter | Description | Typical Range | Unit |
|-----------|-------------|---------------|------|
| SMW | Wilting point | 0.05-0.20 | cm3/cm3 |
| SMFCF | Field capacity | 0.15-0.45 | cm3/cm3 |
| SM0 | Saturation | 0.35-0.55 | cm3/cm3 |
| CRAIRC | Critical air content | 0.02-0.08 | cm3/cm3 |
| K0 | Saturated hydraulic conductivity | 1-50 | cm/day |
| RDMSOL | Maximum rootable depth | 40-200 | cm |
| WAV | Initial available water | 0-100 | cm |

**Milestone**: `m2_water_limits_valid` — SMW < SMFCF < SM0

---

### S3: Weather Data Preparation

**Purpose**: Provide daily meteorological data to the PCSE engine.

**Skill document**: `docs/s3_weather_prep_skill.md`

**Tools**:
- `convert_vic_to_pcse_weather` — VIC forcing → PCSE CSV format
- `create_csv_weather_file` — Generic data → PCSE CSV format
- `validate_weather_data` — Unit and range checks

**CRITICAL UNIT TABLE**:
| Variable | PCSE Unit | DSSAT Unit | VIC Unit | Conversion |
|----------|-----------|------------|----------|------------|
| IRRAD | kJ/m2/day | MJ/m2/day (SRAD) | W/m2 | W/m2 × 86.4 = kJ/m2/day |
| TMIN | C | C | C | none |
| TMAX | C | C | C | none |
| VAP | kPa | - (DEWP in C) | kPa | none |
| WIND | m/s | km/day | m/s | none |
| RAIN | cm/day | mm/day | mm | mm ÷ 10 = cm |

**Milestone**: `m3_units_correct` — IRRAD 5000-35000, RAIN 0-10

---

### S4: Agromanagement Definition

**Purpose**: Define crop calendar, irrigation, and fertilization events.

**Skill document**: `docs/s4_agromanagement_skill.md`

**Tools**:
- `generate_agromanagement_yaml` — Create YAML from user inputs
- `validate_agromanagement` — Check structure and name matching

**YAML structure**:
```yaml
- 2000-10-01:            # campaign start date (datetime.date)
    CropCalendar:
        crop_name: wheat          # CASE SENSITIVE
        variety_name: Winter_wheat_101  # CASE SENSITIVE
        crop_start_date: 2000-10-15
        crop_start_type: sowing   # or 'emergence'
        crop_end_date:            # null = use crop_end_type
        crop_end_type: maturity   # or 'harvest', 'earliest'
        max_duration: 365
    TimedEvents:
    -   event_signal: irrigate
        name: irrigation schedule
        comment: fixed schedule
        events_table:
        - 2001-03-15: {amount: 30, efficiency: 0.7}
        - 2001-04-15: {amount: 30, efficiency: 0.7}
    StateEvents: null
```

**Milestone**: `m4_crop_names_match` — crop_name/variety_name exist in parameter DB

---

### S5: Engine Configuration

**Purpose**: Assemble all components and instantiate the PCSE engine.

**Skill document**: `docs/s5_engine_config_skill.md`

**Tools**:
- `configure_pcse_engine` — Combine params, select engine class
- `validate_engine_config` — Cross-check mode vs data

**Engine classes**:
| Class | Mode | Water Balance | Soil Required | Use Case |
|-------|------|--------------|---------------|----------|
| `Wofost72_PP` | Potential | No | No | Theoretical max yield |
| `Wofost72_WLP_FD` | Water-limited | Yes (free drainage) | Yes | Standard real-world |
| `Wofost72_WLP_CWB` | Water-limited | Yes (+ groundwater) | Yes | High water table areas |

**Milestone**: `m5_engine_instantiated` — Engine object created without exception

---

### S6: Simulation Execution

**Purpose**: Run the WOFOST daily simulation loop.

**Skill document**: `docs/s6_execution_skill.md`

**Tools**:
- `run_wofost_simulation` — Full cell simulation
- `check_simulation_status` — Diagnose post-run status

**Execution**:
```python
engine = Wofost72_WLP_FD(params, weather, agro)
engine.run_till_terminate()
# Or step-by-step:
engine.run(days=1)  # advance one day
```

**DVS progression**: 0 (emergence) → 1 (anthesis) → 2 (maturity)

**Milestone**: `m6_dvs_reached_maturity` — DVS >= 2.0

---

### S7: Output Parsing

**Purpose**: Extract and structure simulation results.

**Skill document**: `docs/s7_output_parsing_skill.md`

**Tools**:
- `parse_wofost_output` — Structure raw engine output
- `export_output_csv` — Export to analysis-ready CSV

**Key output variables**:
| Variable | Description | Unit |
|----------|-------------|------|
| DVS | Development stage | - (0-2) |
| LAI | Leaf area index | m2/m2 |
| TAGP | Total above-ground production | kg/ha |
| TWSO | Total weight storage organs (yield) | kg/ha |
| TWLV | Total weight leaves | kg/ha |
| TWST | Total weight stems | kg/ha |
| TWRT | Total weight roots | kg/ha |
| TRA | Transpiration | cm/day |
| RD | Rooting depth | cm |
| SM | Soil moisture | cm3/cm3 |

**Milestone**: `m7_dataframe_created` — DataFrame with DatetimeIndex

---

### S8: Yield Analysis and Multi-Model Ensemble

**Purpose**: Analyze results, create spatial maps, compare with DSSAT.

**Skill document**: `docs/s8_yield_analysis_skill.md`

**Tools**:
- `compute_gridded_yield` — Aggregate cell outputs to spatial CSV
- `compare_wofost_dssat` — Multi-model ensemble statistics
- `generate_yield_map` — Spatial yield visualization

**Milestone**: `m8_yield_reasonable` — TWSO 500-20000 kg/ha

---

## Diagnostic Triplets Coverage

See `diagnostics/triplets.yaml` for 15 triplets covering:
- YAML indent/parse errors (dt_001, dt_002)
- Unit conversion traps: kJ vs MJ, cm vs mm (dt_003, dt_004)
- Vernalization misconfiguration / DVS stuck (dt_005, dt_006)
- Zero yield silent death (dt_007)
- Simulation mode confusion PP vs WLP (dt_008)
- Soil FC < WP impossible state (dt_009)
- Case sensitivity in crop/variety names (dt_010)
- Weather data gaps (dt_011)
- PCSE API version changes (dt_012)
- AFGEN table non-monotonic (dt_013)
- Max duration too short (dt_014)
- NASAPower API timeout (dt_015)

---

*This workflow document is part of the wofost-pcse-knowledge infrastructure package.*
*8 stages | 17 tools | 8 skill documents | 15 diagnostic triplets*
