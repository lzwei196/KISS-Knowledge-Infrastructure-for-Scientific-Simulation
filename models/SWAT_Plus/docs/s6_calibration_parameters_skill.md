# Calibration Parameter Setup — Skill Document

> **Stage ID**: s6_calibration_parameters
> **Pipeline order**: 6 of 9
> **Depends on**: s2_hru_definition, s4_soil_database

## Purpose

SWAT+ uses a text-based calibration system (calibration.cal) that adjusts model parameters at runtime without modifying individual input files. This is a major improvement over SWAT2012, which required editing soil, groundwater, and HRU files directly. Proper calibration typically improves NSE from <0.3 (uncalibrated) to >0.6 (calibrated). For water quality calibration, hydrology must be calibrated first.

## Prerequisites

Before starting this stage, verify:

- [ ] HRU definition complete (S2) — know which land uses and soils exist
- [ ] Soil database complete (S4) — know baseline soil properties
- [ ] Observed discharge data available for at least the outlet station
- [ ] For water quality calibration: observed N, P, and/or sediment data
- [ ] Understanding of basin characteristics (humid vs arid, forest vs agricultural, flat vs mountainous)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Parameter set | config | Literature / expert judgment / previous calibration | Parameters and their adjustment values |
| Observed discharge | file | Gauging station data | For performance evaluation |
| Basin characteristics | config | From S1 and S2 | Area, dominant land use, climate, topography |

## Procedure

### Step 1: Select initial calibration parameters

Start with the most sensitive hydrology parameters. Recommended initial set:

| Parameter | Description | Range | Change Type | Start Value |
|-----------|-------------|-------|-------------|-------------|
| cn2 | SCS curve number | -25 to +25% | pctchg | 0 (no change) |
| esco | Soil evap compensation | 0.01 - 1.0 | absval | 0.95 |
| awc | Available water capacity | -50 to +50% | pctchg | 0 |
| surlag | Surface runoff lag | 0.05 - 24 | absval | 4.0 |
| alpha_bf | Baseflow recession | 0.0 - 1.0 | absval | 0.048 |
| gw_delay | Groundwater delay (days) | 0 - 500 | absval | 31 |
| perco | Percolation coefficient | 0.0 - 1.0 | absval | 0.5 |
| revap_co | GW revap coefficient | 0.02 - 0.2 | absval | 0.02 |
| lat_ttime | Lateral flow travel (days) | 0 - 180 | absval | 0 |
| canmx | Max canopy storage (mm) | 0 - 100 | absval | 0 |

### Step 2: Generate calibration.cal

```bash
python tools/s6/generate_calibration_file.py
```

calibration.cal format:
```
calibration.cal: written by SWAT+ knowledge infrastructure
  cal_parm       chg_typ     chg_val     cond      sol_l     obj_typ    ...
  cn2            pctchg      -10.000     null      0         hru        ...
  esco           absval      0.850       null      0         hru        ...
  awc            pctchg      15.000      null      0         hru        ...
  alpha_bf       absval      0.100       null      0         aqu        ...
```

Fields:
- `cal_parm`: Parameter name (must match SWAT+ internal name exactly)
- `chg_typ`: absval (set to value), abschg (add value), pctchg (% change)
- `chg_val`: The adjustment value
- `cond`: Condition for conditional adjustment (null = apply to all)
- `sol_l`: Soil layer number (0 = all layers)
- `obj_typ`: Object type (hru, aqu, cha, etc.)

**Expected result**: calibration.cal with initial parameter values.

### Step 3: Validate parameter ranges

```bash
python tools/s6/apply_calibration.py
```

Verify all parameter names are valid SWAT+ variables and values are within physical bounds.

**If this fails**: See diagnostic triplet dt_013.

### Step 4: Calibration strategy

**Manual calibration sequence** (recommended first):
1. **Baseflow**: Adjust alpha_bf, gw_delay, revap_co, flo_min
2. **Surface runoff**: Adjust cn2, surlag
3. **ET**: Adjust esco, epco, canmx
4. **Total water yield**: Fine-tune awc, perco, lat_ttime

**Automated calibration** (after manual gets NSE > 0.3):
- SWAT-CUP with SUFI-2 algorithm
- iPlusQ (SWAT+ specific calibration tool)
- Custom Python script with differential evolution or Bayesian optimization

### Step 5: Water quality calibration (after hydrology)

Only after hydrology NSE > 0.5, calibrate water quality parameters:

| Parameter | Description | Affects |
|-----------|-------------|---------|
| nperco | N percolation coefficient | NO3 in groundwater |
| cdn | Denitrification exponential rate | N removal |
| sdnco | Denitrification threshold water content | N removal |
| pperco | P percolation coefficient | Dissolved P loss |
| phoskd | P soil partitioning coefficient | P in runoff |
| erorgn | Organic N enrichment ratio | Organic N with sediment |
| erorgp | Organic P enrichment ratio | Organic P with sediment |
| usle_p | USLE support practice factor | Sediment yield |

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| calibration.cal | `TxtInOut/calibration.cal` | Valid header + parameter lines; values within ranges |

## Validation Checks

1. **Parameter names valid**: All cal_parm values match SWAT+ internal names.
   - If wrong: SWAT+ silently ignores unknown parameters. See dt_013.

2. **Change type appropriate**: Use pctchg for cn2 and awc (preserve spatial variability), absval for esco, alpha_bf.

3. **Physical bounds**: cn2 change should keep values in [25, 98]; esco in [0, 1]; alpha_bf in [0, 1].

4. **No duplicate parameters**: Each parameter should appear at most once per condition set.

## Common Pitfalls

> **PITFALL**: Using absval for CN2 (destroys spatial variability)
> CN2 varies by land use and soil. Using absval sets ALL HRUs to the same CN2, removing the land use signal. The model still runs but runoff generation is unrealistic.
> **Do this instead**: Always use pctchg for cn2 and awc. Example: pctchg -10 reduces all CN2 values by 10%.
> See diagnostic triplet dt_013.

> **PITFALL**: Misspelled parameter name silently ignored
> If you write "cn_2" instead of "cn2", SWAT+ ignores it without warning. The calibration has no effect and results match the uncalibrated run.
> **Do this instead**: Use the exact parameter names from SWAT+ documentation. Validate with apply_calibration tool.

> **PITFALL**: Calibrating water quality before hydrology
> If the water balance is wrong, nutrient transport is also wrong. Calibrating N/P parameters to match observations when discharge is wrong produces compensating errors.
> **Do this instead**: First calibrate hydrology to NSE > 0.5, then calibrate water quality.

---

*This skill document is part of the SWAT+ knowledge infrastructure.*
*Stage 6 of 9 | Tools used: generate_calibration_file, apply_calibration | Related triplets: dt_013*
