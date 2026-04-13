# Model Assembly -- Skill Document

> **Stage ID**: s7_model_assembly
> **Pipeline order**: 7 of 10
> **Depends on**: s1_crop_selection, s2_soil_profile, s3_weather_prep, s4_initial_conditions, s5_irrigation, s6_field_management

## Purpose

Combine all prepared components (crop, soil, weather, initial conditions, irrigation, field management) into a single AquaCropModel object ready for execution. This stage validates compatibility between components and sets simulation timing.

## Prerequisites

- [ ] Crop object created (S1)
- [ ] Soil object created (S2)
- [ ] Weather DataFrame prepared with ET0 (S3)
- [ ] InitialWaterContent object created (S4)
- [ ] IrrigationManagement object created (S5, optional -- defaults to rainfed)
- [ ] FieldMngt object created (S6, optional -- defaults to no management)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| sim_start_time | string | User | Simulation start date, format 'YYYY/MM/DD' |
| sim_end_time | string | User | Simulation end date, format 'YYYY/MM/DD' |
| weather_df | DataFrame | S3 | Daily weather data |
| soil | Soil | S2 | Soil profile |
| crop | Crop | S1 | Crop parameters |
| initial_water_content | InitialWaterContent | S4 | Initial soil water |
| irrigation_management | IrrigationManagement | S5 | Irrigation strategy (optional) |
| field_management | FieldMngt | S6 | Field management (optional) |
| off_season | bool | User | Simulate off-season periods (default False) |

## Procedure

### Step 1: Verify date format

Dates MUST use **slash separators**: `'YYYY/MM/DD'`

```python
sim_start = '2000/01/01'   # CORRECT
sim_end   = '2005/12/31'   # CORRECT
# sim_start = '2000-01-01'  # WRONG -- raises ValueError
```

### Step 2: Verify weather coverage

The weather DataFrame must cover the entire simulation period:
```python
assert weather_df.Date.min() <= pd.Timestamp(sim_start)
assert weather_df.Date.max() >= pd.Timestamp(sim_end)
```

### Step 3: Assemble model

```python
from aquacrop import AquaCropModel

model = AquaCropModel(
    sim_start_time=sim_start,
    sim_end_time=sim_end,
    weather_df=weather_df,
    soil=soil,
    crop=crop,
    initial_water_content=iwc,
    irrigation_management=irr,     # defaults to rainfed if omitted
    field_management=field,         # defaults to FieldMngt() if omitted
    off_season=False,               # True for multi-year continuous simulation
)
```

### Step 4: Pre-flight checks

Run tool `validate_model_config`:
- Date format correct (slashes not dashes)
- Weather covers simulation period
- Planting date falls within simulation period
- Soil depth >= crop max root depth
- IWC layers match soil layers

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| AquaCropModel instance | in-memory | No ValueError raised during construction |

## Validation Checks

1. **Date format**: Uses '/' separator. See dt_009.
2. **Weather coverage**: DataFrame dates span simulation period
3. **Planting within sim**: Crop planting date falls between start and end
4. **Multi-season**: If `off_season=False` and sim spans multiple years, only one growing season is simulated per year

## Common Pitfalls

> **PITFALL**: Date format with dashes instead of slashes
> `'2000-01-01'` raises ValueError: "sim_start_time format must be 'YYYY/MM/DD'".
> **Do this instead**: Always use slashes: `'2000/01/01'`.
> See diagnostic triplet dt_009.

> **PITFALL**: Simulation period does not cover planting to maturity
> If sim_end_time is before expected maturity, the crop will not complete its cycle and yield will be zero or partial.
> **Do this instead**: Ensure sim_end_time is at least ~200 days after planting for grain crops.

> **PITFALL**: off_season=False skips inter-season periods
> With off_season=False (default), the model jumps from harvest to next planting. For continuous soil moisture tracking, set off_season=True.

---

*This skill document is part of the aquacrop-ospy-knowledge infrastructure.*
*Stage 7 of 10 | Tools used: assemble_model, validate_model_config | Related triplets: dt_009, dt_010*
