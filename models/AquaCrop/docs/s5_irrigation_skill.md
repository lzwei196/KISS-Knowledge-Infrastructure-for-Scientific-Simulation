# Irrigation Management -- Skill Document

> **Stage ID**: s5_irrigation
> **Pipeline order**: 5 of 10
> **Depends on**: none

## Purpose

Define the irrigation strategy that determines when, how much, and how water is applied to the crop. This is the **core analytical capability** of AquaCrop -- the model was specifically designed for water productivity analysis and deficit irrigation optimization. Unlike DSSAT/WOFOST which treat irrigation as a simple management input, AquaCrop's water-driven growth engine makes irrigation strategy the primary control variable for yield optimization.

## Prerequisites

- [ ] Knowledge of available water supply (unlimited, limited, or specific allocation)
- [ ] Decision on irrigation approach (rainfed, full irrigation, deficit, scheduled)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| irrigation_method | int | User decision | 0=rainfed, 1=SMT, 2=interval, 3=schedule, 4=net, 5=constant |
| SMT | list of 4 | User optimization | Soil moisture targets per growth stage (% TAW), for method=1 |
| IrrInterval | int | User decision | Days between irrigation events, for method=2 |
| Schedule | DataFrame | User/historical | Dates and depths, for method=3 |
| NetIrrSMT | float | User decision | Net irrigation threshold (% TAW), for method=4 |
| depth | float | User decision | Constant daily depth (mm), for method=5 |
| WetSurf | float | Equipment specs | Soil surface wetted (%, default 100) |
| AppEff | float | Equipment specs | Application efficiency (%, default 100) |
| MaxIrr | float | System capacity | Maximum daily application (mm, default 25) |
| MaxIrrSeason | float | Water allocation | Maximum seasonal application (mm, default 10000) |

## Procedure

### Step 1: Select irrigation method

```python
from aquacrop import IrrigationManagement

# Method 0: Rainfed (baseline reference)
irr = IrrigationManagement(irrigation_method=0)

# Method 1: Soil Moisture Targets (RECOMMENDED for optimization)
# SMT = [stage1, stage2, stage3, stage4] as % of Total Available Water
# Stages: emergence-anthesis, anthesis-maxCC, maxCC-senescence, senescence-maturity
irr = IrrigationManagement(irrigation_method=1, SMT=[70, 80, 80, 70])

# Method 2: Fixed interval
irr = IrrigationManagement(irrigation_method=2, IrrInterval=7)

# Method 3: Predefined schedule
import pandas as pd
schedule = pd.DataFrame({
    'Date': pd.to_datetime(['2000/06/15', '2000/07/01', '2000/07/15']),
    'Depth': [25, 30, 25]  # mm per event
})
irr = IrrigationManagement(irrigation_method=3, Schedule=schedule)

# Method 4: Net irrigation (maintain soil at threshold)
irr = IrrigationManagement(irrigation_method=4, NetIrrSMT=80)

# Method 5: Constant daily depth
irr = IrrigationManagement(irrigation_method=5, depth=5)  # mm/day
```

### Step 2: Configure application parameters

```python
irr = IrrigationManagement(
    irrigation_method=1,
    SMT=[70, 80, 80, 70],
    WetSurf=100,       # % of soil surface wetted (100 for flood, 30-50 for drip)
    AppEff=90,          # % application efficiency (60-70 flood, 85-95 drip)
    MaxIrr=25,          # mm/day max application capacity
    MaxIrrSeason=500,   # mm/season allocation limit
)
```

### Step 3: Deficit irrigation optimization (AquaCrop's unique strength)

To find optimal SMT thresholds, run multiple scenarios:

```python
results = []
for smt in range(0, 101, 10):
    irr = IrrigationManagement(irrigation_method=1, SMT=[smt]*4)
    model = AquaCropModel(sim_start_time, sim_end_time, weather_df,
                          soil, crop, iwc, irrigation_management=irr)
    model.run_model(till_termination=True)
    stats = model.get_simulation_results()
    flux = model.get_water_flux()
    results.append({
        'SMT': smt,
        'Yield': stats['Dry yield (tonne/ha)'].iloc[0],
        'Irrigation': flux['IrrDay'].sum(),
        'ET': flux['Es'].sum() + flux['Tr'].sum()
    })
```

Run tool `optimize_deficit_irrigation` for automated sweep.

### Step 4: Validate irrigation setup

- Method 1: All SMT values should be 0-100
- Method 3: Schedule dates must fall within simulation period
- Method 3: Schedule DataFrame must have columns 'Date' and 'Depth'
- MaxIrr must be > 0 if irrigation is used

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| IrrigationManagement object | in-memory | `irr.irrigation_method` is valid integer 0-5 |

## Validation Checks

1. **Method code**: `irrigation_method in [0, 1, 2, 3, 4, 5]`
2. **SMT range**: All values 0-100 for method=1
3. **Schedule format**: DataFrame with Date and Depth columns for method=3. See dt_013.
4. **Efficiency**: `0 < AppEff <= 100`

## Common Pitfalls

> **PITFALL**: SMT values > 100 or < 0
> SMT represents percentage of Total Available Water (TAW = FC - WP). Values > 100 mean soil is above FC (unlikely to sustain). Values < 0 are meaningless.
> **Do this instead**: Keep SMT in range 0-100. Use 100 for full irrigation, 0 for rainfed.

> **PITFALL**: Schedule DataFrame missing Date column or wrong dtype
> The Schedule must be a pandas DataFrame with a 'Date' column of pd.Timestamp type and a 'Depth' column of float. Wrong column names or types cause runtime errors.
> See diagnostic triplet dt_013.

> **PITFALL**: MaxIrr too low for deficit irrigation recovery
> If MaxIrr (default 25 mm/day) is too low, the model cannot apply enough water to restore soil to SMT threshold in a single event. Multiple consecutive irrigation days result.
> **Do this instead**: Set MaxIrr to at least the depth needed to refill the top soil compartments from current depletion to SMT.

---

*This skill document is part of the aquacrop-ospy-knowledge infrastructure.*
*Stage 5 of 10 | Tools used: create_irrigation_management, optimize_deficit_irrigation | Related triplets: dt_013*
