# Land Use and Management Configuration — Skill Document

> **Stage ID**: s5_landuse_management
> **Pipeline order**: 5 of 9
> **Depends on**: s2_hru_definition

## Purpose

Management schedules define human interventions (planting, fertilization, irrigation, tillage, harvest) that control crop growth, nutrient input, and land surface conditions. Without management schedules, agricultural HRUs have no crops growing and no nutrient inputs — water yield may be roughly correct, but nutrient loads are meaningless. This stage also configures the landuse.lum lookup that connects each HRU's land use code to its management schedule.

## Prerequisites

Before starting this stage, verify:

- [ ] HRU definition complete (S2) — land use types identified
- [ ] plants.plt database available (typically use SWAT+ default database)
- [ ] Fertilizer types defined in fertilizer.frt (use default or customize)
- [ ] Tillage operations defined in tillage.til (use default or customize)
- [ ] Crop calendar information: planting dates, harvest dates by crop type and region

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Land use types | config | From S2 HRU definition | List of unique land use codes in basin |
| Crop calendar | config | Literature / local data / global datasets | Planting and harvest DOY by crop |
| Fertilizer rates | config | Literature / NPKGRIDS / local data | N/P/K application rates (kg/ha) |
| Default databases | files | SWAT+ distribution | plants.plt, fertilizer.frt, tillage.til |

## Procedure

### Step 1: Review land use types and match to plants.plt

List all land use codes from hru-data.hru. Verify each code exists in plants.plt. Common codes:
- Crops: `CORN`, `SOYB`, `WWHT`, `SWHT`, `RICE`, `COTT`, `SUGC`, `AGRL`
- Forest: `FRSD`, `FRSE`, `FRST`
- Grassland: `PAST`, `RNGE`, `HAY`
- Urban: `URBN`, `URHD`, `URLD`, `URMD`
- Water/Wetland: `WATR`, `WETL`

**Expected result**: All land use codes have matching plants.plt entries.

### Step 2: Build management schedules

```bash
python tools/s5/build_management_schedules.py
```

For each agricultural land use, define an operation sequence in management.sch:

```
management.sch: written by SWAT+ knowledge infrastructure
  name             numb_ops  numb_auto
  corn_grain       6         0
  op_typ    mon  day  hu_sch    op_data1      op_data2      op_data3
  tillage   4    1    0.000     field_cultivator  null       null
  plant     4    15   0.000     corn          null           null
  fert      5    1    0.000     elem_n        null           null
  fert      6    15   0.000     elem_n        null           null
  harvest   10   15   1.200     corn          grain          null
  kill      10   16   0.000     null          null           null
```

Operation types: `tillage`, `plant`, `fert`, `irrigate`, `harvest`, `kill`, `graze`, `burn`

**Expected result**: management.sch with operation sequences for all agricultural land uses.

### Step 3: Configure fertilizer applications

Fertilizer operations reference fertilizer.frt entries. Key fertilizer types:
- `elem_n`: Elemental nitrogen (46-0-0, like urea)
- `elem_p`: Elemental phosphorus (0-46-0, like TSP)
- `28-0-0`: UAN solution
- Organic: `beef_fr` (beef feedlot manure), `dairy_fr`, `poultry`

Typical N application rates:
- Corn: 150-200 kg N/ha (split into 2-3 applications)
- Winter wheat: 100-150 kg N/ha
- Soybean: 0 kg N/ha (nitrogen fixing)

**Expected result**: Fertilizer operations with reasonable rates.

### Step 4: Configure landuse.lum

```bash
python tools/s5/configure_landuse.py
```

landuse.lum links each land use code to:
- Management schedule name (from management.sch)
- CN2 table reference (from cntable.lum)
- Urban parameters (from urban.urb, if urban HRUs)
- Tile drain parameters (if applicable)

**Expected result**: landuse.lum with valid references for all land use types.

### Step 5: Verify management sequence logic

Check that operations are in correct temporal order:
- Tillage before planting
- Planting before fertilization
- Fertilization before harvest
- Harvest before kill

**Expected result**: No illogical operation ordering.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| management.sch | `TxtInOut/management.sch` | Valid operation sequences; plant before harvest |
| landuse.lum | `TxtInOut/landuse.lum` | All land uses have management references |
| cntable.lum | `TxtInOut/cntable.lum` | CN2 values by land use and hydrologic group |

## Validation Checks

1. **Planting before harvest**: In every management schedule, planting must precede harvest.
   - If violated: See diagnostic triplet dt_011

2. **Fertilizer rates reasonable**: N application < 500 kg/ha, P < 200 kg/ha per event.

3. **All landuse.lum references valid**: Every management schedule name in landuse.lum exists in management.sch.

4. **CN2 values in range**: CN2 in [25, 98] for all land use / hydrologic group combinations.

## Common Pitfalls

> **PITFALL**: Missing management schedule for agricultural HRUs
> If an agricultural HRU has no management schedule, no crops are planted and no fertilizer applied. Water yield may be approximately correct, but ET is wrong (bare soil vs crop canopy) and nutrient loads are zero.
> **Do this instead**: Ensure every agricultural land use code has a management schedule in landuse.lum.
> See diagnostic triplet dt_011.

> **PITFALL**: Harvest heat unit (hu_sch) too high
> If the heat unit fraction for harvest is set too high (e.g., 1.5), the crop may never reach that maturity level in cold years, causing no harvest and continuous growth into winter.
> **Do this instead**: Use hu_sch = 1.0-1.2 for harvest operations.

> **PITFALL**: Wrong crop name in management.sch
> SWAT+ silently ignores unrecognized crop names. The plant operation does nothing, leaving bare soil.
> **Do this instead**: Cross-check all crop names against plants.plt entries exactly.

---

*This skill document is part of the SWAT+ knowledge infrastructure.*
*Stage 5 of 9 | Tools used: build_management_schedules, configure_landuse | Related triplets: dt_011*
