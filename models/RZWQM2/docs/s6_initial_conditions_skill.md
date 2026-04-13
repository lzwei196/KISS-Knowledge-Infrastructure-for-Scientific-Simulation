# Skill Document: Initial Conditions Setup (S6)

**Stage:** s6_initial_conditions
**Pipeline Order:** 6
**Depends On:** s4_soil_setup (horizon count and depths must match RZWQM.dat)
**Tool:** `write_initial_conditions`

---

## Purpose

Configure the initial state of the soil profile at the start of the simulation by writing to `RZINIT.dat`. This file specifies the starting values for three categories of state variables: (1) soil water content or tension and temperature for each horizon, (2) soil chemistry parameters (pH, CEC, organic carbon) for each horizon, and (3) nutrient pools (NO3, NH4, urea, organic N) for each horizon.

These initial conditions establish the baseline state from which the simulation evolves. While the model will eventually equilibrate to forcing conditions during a warm-up period, unreasonable initial values can cause numerical instability in early time steps or bias the warm-up trajectory. For most applications, the default placeholder values work adequately if a sufficient warm-up period (1-3 years) precedes the analysis period.

**Critical constraint:** The number of horizons in RZINIT.dat must exactly match the number of horizons defined in RZWQM.dat. A mismatch causes a fatal crash.

---

## Prerequisites

1. Soil horizons have been defined in RZWQM.dat (S4 complete).
2. The number of horizons is known and consistent between RZWQM.dat and the planned RZINIT.dat.
3. RZINIT.dat template exists in the scenario directory.
4. Python environment with access to `rzwqm_file.py` (specifically the `RZWQM` class and its RZINIT write methods).

---

## Inputs

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `project_path` | string (directory) | RZWQM2 project root | `/Users/leo/Desktop/RZWQM2/projects/` |
| `station_id` | string | Scenario identifier | `534` |
| `num_horizons` | int | Number of soil horizons (must match RZWQM.dat) | `5` |

### Optional Measured Data

If available, these can replace the default placeholder values:

| Variable | Unit | Description | Per Horizon? |
|----------|------|-------------|-------------|
| Initial soil tension | cm (negative) | Soil water tension at start | Yes |
| Initial temperature | degrees C | Soil temperature at start | Yes |
| pH | -- | Soil pH | Yes |
| CEC | meq/100g | Cation exchange capacity | Yes |
| Organic carbon | % | Soil organic carbon content | Yes |
| NO3-N | ug/g or kg/ha | Initial nitrate | Yes |
| NH4-N | ug/g or kg/ha | Initial ammonium | Yes |

---

## Procedure

### Step 1: Understand RZINIT.dat Structure

The RZINIT.dat file has three major sections, each identified by section markers:

#### Section 1: Water Content/Tension and Temperature

Located between `'=            ... repeat record 2 for all horizons'` and `'==                   S O I L   C H E M I S T R Y                      =='`.

**Format:**
```
{flag1} {flag2}
{tension_or_wc_1} {temperature_1}
{tension_or_wc_2} {temperature_2}
...
```

- **Line 1:** Two flags:
  - Flag 1: `0` = tension input (cm, negative values for unsaturated), `1` = volumetric water content input
  - Flag 2: `0` = standard mode
- **Lines 2 to N+1:** One line per horizon with 2 values:
  - Value 1: Soil water tension (cm, typically negative) or water content (fraction)
  - Value 2: Soil temperature (degrees C)

#### Section 2: Soil Chemistry

Located between `'=    (Repeat records 1-3 for each soil horizon)'` and `'==                      N U T R I E N T                               =='`.

**Format:** 3 lines per horizon:

**Line 1 (12 values):**
```
{pH}   {T_or_F}  {F}  {F} {param1}  {CEC}  {0.0}  {0.0}  {0.0}  {0.0}  {0.0}  {OC}
```
- `pH`: Soil pH
- `T_or_F` flags: Typically `T  F  F`
- `param1`: Chemical parameter (~0.000275)
- `CEC`: Cation exchange capacity
- `OC`: Organic carbon fraction

**Line 2 (5 values):**
```
{param1}  {param2}  {param3}  {param4}  {param5}
```
- CEC-related parameters (cation fractions, etc.)

**Line 3 (3 values):**
```
{param1}  {0.0}  {0.0}
```
- Additional chemical parameter (typically similar to CEC/fraction values)

#### Section 3: Nutrients

Located between `'=       ...repeat For each horizon'` and `'==                      P E S T I C I D E S                           =='`.

**Format:** 1 line per horizon with 18 values:
```
{NO3} {NH4} {urea} {org_N_pool1} {org_N_pool2} {0.0} {org_N_pool3} {org_N_pool4} {org_N_pool5} {0.0} {param1} {param2} {0.0} {0.0} {0.0} {0.0} {0.0} {param3}
```

Key nutrient parameters:
- Values 1-3: Inorganic N (NO3, NH4, urea) in ug/g
- Values 4-5: Organic N pools (fast, slow decomposition) in ug/g
- Values 7-9: Additional organic N pools in ug/g
- Value 18: Typically a flag or rate constant (e.g., `4.0`)

### Step 2: Write Water and Temperature Initial Conditions

```python
from rzwqm_file import RZWQM

rz = RZWQM(project_path, station_id)

# Create a list representing horizons (just needs length to match num_horizons)
horizon_list = list(range(1, num_horizons + 1))

rz.write_new_soil_init_water_and_temp(horizon_list)
```

The default implementation creates tension-based initial conditions:
- Flag line: `0 0` (tension mode, standard)
- For each horizon except the last: tension = `-(num_horizons - 1 - i) * 10` cm, temperature = `10.0` C
- For the last (deepest) horizon: tension = `0.0` cm (saturated), temperature = `15.0` C

This creates a reasonable initial moisture profile where the soil is drier near the surface and wetter (approaching saturation) at the bottom.

### Step 3: Write Chemistry Initial Conditions

```python
rz.write_new_soil_init_chemistry(horizon_list)
```

The default implementation uses placeholder values from a dictionary of 4 template horizons:

| Horizon | pH | CEC | OC | Notes |
|---------|-----|-----|------|-------|
| 1 | 6.91 | 20.1 | 0.07 | Topsoil |
| 2 | 6.91 | 20.1 | 0.07 | Same as horizon 1 |
| 3 | 6.87 | 20.1 | 0.07 | Slightly lower pH |
| 4+ | 7.01 | 30.1 | 0.07 | Subsoil (higher pH, CEC) |

If more than 4 horizons are specified, horizons 5+ use the same values as horizon 4. If fewer than 4 horizons, only the first N templates are used.

### Step 4: Write Nutrient Initial Conditions

```python
rz.write_new_soil_init_nutrient(horizon_list)
```

The default implementation uses placeholder nutrient values:

| Horizon | NO3 | NH4 | Urea | Org N Pool 1 | Org N Pool 2 |
|---------|------|------|------|-------------|-------------|
| 1 | 74.1 | 14.5 | 243.8 | 1910.8 | 10000.0 |
| 2 | 74.1 | 14.5 | 243.8 | 1910.8 | 10000.0 |
| 3 | 13.7 | 42.4 | 172.7 | 1839.4 | 8502.4 |
| 4+ | 9.5 | 23.7 | 121.3 | 1273.9 | 5901.6 |

Horizons beyond 4 repeat the values from horizon 4.

### Step 5: Verify Horizon Count Consistency

```python
# Verify RZWQM.dat and RZINIT.dat have the same number of horizons
rz_check = RZWQM(project_path, station_id)
dat_horizons = rz_check.return_number_of_soil_horizons()

# Count RZINIT sections
init_data = rz_check.init_data
water_head, water_end = rz_check.line_of_init_soil_water_and_temp()
# Lines between head and end: flag line + N horizon lines = N+1
init_water_lines = water_end - water_head + 1
init_horizons = init_water_lines - 1  # subtract flag line

assert dat_horizons == init_horizons, \
    f"RZWQM.dat has {dat_horizons} horizons but RZINIT.dat has {init_horizons}"
```

---

## Expected Outputs

- **Modified file:** `{project_path}/{station_id}/RZINIT.dat`
- **Sections modified:**
  - Water/temperature section: 1 flag line + N horizon lines (N = number of horizons)
  - Chemistry section: 3N lines (3 lines per horizon)
  - Nutrient section: N lines (1 line per horizon with 18 values each)

---

## Validation Checks

1. **Horizon count match:** The number of data entries in each section of RZINIT.dat must equal the number of horizons in RZWQM.dat. This is the single most important validation check.
2. **Tension values:** If using tension mode (flag=0), values should be negative (except possibly the bottom horizon which may be 0 for saturated conditions). Typical range: -15000 to 0 cm.
3. **Temperature values:** Should be physically reasonable for the region (e.g., 0-30 degrees C for temperate regions). The bottom horizon temperature often approximates the annual mean air temperature.
4. **pH range:** Should be between 3.0 and 10.0 for most soils.
5. **Organic carbon:** Should be between 0 and 15% (typically 1-5% for topsoil, decreasing with depth).
6. **Nutrient values:** NO3 and NH4 should be non-negative.

---

## Common Pitfalls

### PITFALL 1: Number of Horizons Does Not Match RZWQM.dat (FATAL)
**Severity:** Fatal -- the model crashes with an array bounds error or reads incorrect data.
**Symptom:** Segmentation fault, Fortran runtime error, or bizarre output values.
**Cause:** RZWQM.dat was modified to have a different number of horizons than RZINIT.dat. This commonly happens when horizons are added or removed in S4 without updating S6.
**Fix:** Always run S6 (write_initial_conditions) after any change to horizon count in S4. Verify the match programmatically before running the model.

### PITFALL 2: Default Values Not Appropriate for Study Site
**Severity:** Minor if warm-up period is sufficient; moderate if analysis begins immediately.
**Cause:** The placeholder values (pH ~7, moderate CEC, generic nutrient pools) may not represent the actual site. For example, an acidic soil with pH 4.5 starts at pH 7 in the defaults.
**Fix:** If site-specific soil chemistry and nutrient data are available, replace the placeholder values. If not, use a warm-up period of 2-3 years before the analysis period to allow the model to equilibrate.

### PITFALL 3: Forgetting to Update After Horizon Changes
**Severity:** Fatal (see Pitfall 1).
**Cause:** During iterative model setup (e.g., trying different soil profiles), the operator changes horizons in RZWQM.dat but forgets to regenerate RZINIT.dat.
**Fix:** Establish a workflow rule: any time `write_soil_horizon_depth_to_dat` or `insert_new_horizon_to_existing_dat_file` is called, immediately follow with `write_new_soil_init_water_and_temp`, `write_new_soil_init_chemistry`, and `write_new_soil_init_nutrient`.

### PITFALL 4: Water Content Mode vs Tension Mode Confusion
**Severity:** Moderate -- incorrect initial moisture distribution.
**Cause:** Setting flag1=1 (water content mode) but providing tension values, or vice versa.
**Fix:** The default implementation uses flag `0 0` (tension mode). If providing measured volumetric water content data, change the flag to `1 0` and ensure values are in the range 0.0 to porosity.
