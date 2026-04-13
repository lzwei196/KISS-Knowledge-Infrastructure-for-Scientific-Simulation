# Output Parsing — Skill Document

> **Stage ID**: s7_output_parsing
> **Pipeline order**: 7 of 8
> **Depends on**: s6_execution

## Purpose

Extract and structure WOFOST simulation results from the engine into analysis-ready formats. PCSE stores results internally and provides two retrieval methods: `get_output()` for daily time series and `get_summary_output()` for season-level summaries. The raw output is a list of Python dictionaries that must be converted to pandas DataFrames for analysis and CSV for storage.

## Prerequisites

- [ ] PCSE engine has completed simulation (Stage 6)
- [ ] Engine is still in memory (not garbage collected)
- [ ] pandas installed

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| engine | Wofost72_* | Stage 6 | Completed PCSE engine object |

## Procedure

### Step 1: Retrieve daily output

```python
output = engine.get_output()
# Returns: list of dicts, each dict is one day's output
# Keys depend on engine configuration but typically include:
# 'day', 'DVS', 'LAI', 'TAGP', 'TWSO', 'TWLV', 'TWST', 'TWRT',
# 'TRA', 'RD', 'SM', 'WWLOW'
```

**Expected result**: Non-empty list. Length equals number of simulation days.

### Step 2: Convert to pandas DataFrame

```python
import pandas as pd

df = pd.DataFrame(output)
df = df.set_index('day')
df.index = pd.to_datetime(df.index)

print(f"Simulation period: {df.index[0]} to {df.index[-1]}")
print(f"Number of days: {len(df)}")
print(f"Columns: {list(df.columns)}")
```

### Step 3: Retrieve summary output

```python
summary = engine.get_summary_output()
# Returns: list of dicts with season-level metrics
# Keys typically include:
# 'DOE' (date of emergence), 'DOA' (date of anthesis),
# 'DOM' (date of maturity), 'DOH' (date of harvest),
# 'TWSO' (yield kg/ha), 'TAGP' (total biomass kg/ha),
# 'LAIMAX' (max LAI), 'CTRAT' (cumulative transpiration),
# 'DOV' (date of vernalization complete, if applicable)

for item in summary:
    for key, value in item.items():
        print(f"  {key}: {value}")
```

### Step 4: Extract key metrics

```python
# Final yield
yield_kgha = df['TWSO'].iloc[-1]

# Phenology dates
doe = summary[0].get('DOE')  # emergence
doa = summary[0].get('DOA')  # anthesis
dom = summary[0].get('DOM')  # maturity

# Growing season metrics
lai_max = df['LAI'].max()
tagp_final = df['TAGP'].iloc[-1]
harvest_index = yield_kgha / tagp_final if tagp_final > 0 else 0

print(f"Yield: {yield_kgha:.0f} kg/ha")
print(f"Emergence: {doe}, Anthesis: {doa}, Maturity: {dom}")
print(f"Max LAI: {lai_max:.2f}")
print(f"Total biomass: {tagp_final:.0f} kg/ha")
print(f"Harvest index: {harvest_index:.3f}")
```

### Step 5: Export to CSV

```python
output_csv = f'outputs/{run_name}/wofost/daily_output_{lat}_{lon}.csv'
df.to_csv(output_csv)

# Export summary
import json
summary_json = f'outputs/{run_name}/wofost/summary_{lat}_{lon}.json'
with open(summary_json, 'w') as f:
    # Convert dates to strings for JSON serialization
    summary_serializable = []
    for item in summary:
        item_str = {}
        for k, v in item.items():
            item_str[k] = str(v) if hasattr(v, 'strftime') else v
        summary_serializable.append(item_str)
    json.dump(summary_serializable, f, indent=2)
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Daily output CSV | `outputs/{run}/wofost/daily_output_{lat}_{lon}.csv` | Has columns DVS, LAI, TAGP, TWSO; rows = sim days |
| Summary JSON | `outputs/{run}/wofost/summary_{lat}_{lon}.json` | Contains TWSO, DOE, DOA, DOM |

## Validation Checks

1. **Output non-empty**: `len(output) > 0`
   - If empty: Simulation did not produce any daily output — check if engine was run

2. **DVS progression**: DVS should monotonically increase from ~0 to ~2
   - If DVS oscillates: Parameter error in thermal time accumulation

3. **TWSO monotonically increasing after DVS=1**: Storage organ weight should only increase after anthesis
   - If TWSO decreases: Unusual — check for leaf-to-storage reallocation parameters

4. **LAI profile**: Should increase, peak, then decrease
   - If LAI stays at 0 throughout: Emergence never occurred

5. **Summary dates ordered**: DOE < DOA < DOM
   - If DOA is None: Anthesis never reached (DVS < 1.0)

## Common Pitfalls

> **PITFALL**: Calling get_output() before run_till_terminate()
> If you call get_output() before running the simulation, it returns an empty list with no error.
> **Do this instead**: Always run the simulation first, then retrieve output.

> **PITFALL**: Date serialization in JSON
> datetime.date objects are not JSON-serializable. Dumping summary output to JSON without date conversion causes a TypeError.
> **Do this instead**: Convert dates to strings before JSON serialization.

> **PITFALL**: Confusing TWSO with TAGP
> TWSO is grain/tuber yield (storage organs only). TAGP is total above-ground production (leaves + stems + storage organs). For yield reporting, always use TWSO.

---

*This skill document is part of the wofost-pcse-knowledge infrastructure.*
*Stage 7 of 8 | Tools: parse_wofost_output, export_output_csv | Related triplets: none specific*
