# S3: Forcing and Boundary Conditions

## Purpose

Convert meteorological forcing data (precipitation, evapotranspiration) and
hydrological observations (river stage, pumping rates) into PFLOTRAN boundary
conditions. This stage defines the water inputs and outputs at domain boundaries.

## Inputs

| Input | Format | Source | Units |
|---|---|---|---|
| Precipitation | NetCDF | CMFD, ERA5, MSWX | mm/day or mm/3hr |
| Evapotranspiration | NetCDF | MODIS, GLEAM | mm/day |
| River stage | CSV / NetCDF | CaMa-Flood, gauge | m |
| Pumping rates | CSV | Well records | m^3/day |

## Outputs

| Output | Format | Used By |
|---|---|---|
| Recharge time series | PFLOTRAN dataset (text) | s5_input_deck_assembly |
| FLOW_CONDITION blocks | PFLOTRAN .in text | s5_input_deck_assembly |
| BOUNDARY_CONDITION blocks | PFLOTRAN .in text | s5_input_deck_assembly |
| SOURCE_SINK blocks (wells) | PFLOTRAN .in text | s5_input_deck_assembly |

## Procedure

### Step 1: Estimate Recharge from Precipitation

Recharge is the fraction of precipitation that infiltrates past the root zone:

```
recharge = precipitation * infiltration_fraction - ET
```

Typical infiltration fractions:
- Sand/gravel: 0.20 – 0.40
- Loam: 0.10 – 0.20
- Clay: 0.02 – 0.10
- Urban: 0.01 – 0.05

### Step 2: Convert Units (CRITICAL)

**Precipitation/Recharge: mm/day → m/s**

```
recharge_m_s = recharge_mm_day * 1.1574074e-8
```

| Source Unit | Conversion Factor | PFLOTRAN Unit |
|---|---|---|
| mm/day | × 1.1574074e-8 | m/s |
| mm/yr | × 3.1710e-11 | m/s |
| mm/3hr | × 9.2593e-8 | m/s |
| m/day | × 1.1574074e-5 | m/s |

**TRAP dt_002**: Forgetting the mm→m conversion (factor 1000) causes the domain
to flood. A recharge of 100 mm/yr = 3.17e-9 m/s. If entered as 100 m/s, the
domain fills in milliseconds.

**PFLOTRAN inline units alternative**:

```
LIQUID_FLUX 100.d0 mm/yr    ! PFLOTRAN converts internally
```

This is safer but not available for all datasets/time-varying BCs.

### Step 3: Format Time-Varying Boundary Conditions

For transient recharge from a dataset file:

```
FLOW_CONDITION recharge
  TYPE
    LIQUID_FLUX NEUMANN
  /
  LIQUID_FLUX FILE recharge_timeseries.txt
END
```

Dataset file format (space-delimited, time in seconds):
```
0.0 3.17e-09
86400.0 5.21e-09
172800.0 1.02e-09
...
```

### Step 4: River Boundary Conditions

For river stages (Dirichlet BC):

```
FLOW_CONDITION river_stage
  TYPE
    LIQUID_PRESSURE DIRICHLET
  /
  LIQUID_PRESSURE FILE river_pressure.txt
END
```

Convert river stage (m) to pressure (Pa):
```
P = rho * g * (stage - z_cell) + P_atm
P = 998.2 * 9.80665 * (stage - z_cell) + 101325
```

**TRAP dt_003**: Using stage in meters directly as pressure gives ~1e1 Pa
instead of ~1e5 Pa, resulting in negligible gradient.

### Step 5: Pumping Wells

```
FLOW_CONDITION pumping_well
  TYPE
    RATE SCALED_VOLUMETRIC_RATE
  /
  RATE -1.157e-3   ! negative = extraction, m^3/s
END

SOURCE_SINK
  FLOW_CONDITION pumping_well
  REGION well_1
END
```

Convert pumping rate: m^3/day → m^3/s: divide by 86400

### Step 6: Assign to Regions

```
BOUNDARY_CONDITION top_recharge
  FLOW_CONDITION recharge
  REGION top
END

BOUNDARY_CONDITION river_bc
  FLOW_CONDITION river_stage
  REGION river_cells
END
```

### Step 7: ET as Root-Zone SOURCE_SINK (1D Vadose Column)

For vadose-zone column validation against FLUXNET soil moisture, apply ET
as a distributed volumetric sink using `SCALED_VOLUMETRIC_RATE VOLUME`.
This avoids single-cell depletion that occurs when ET is applied as a
negative Neumann top BC.

**Physical basis**: PFLOTRAN divides the specified rate [m³/s] by the SOURCE_SINK
region volume [m³] to get a uniform per-volume extraction rate [1/s], then
applies it to every cell in the region.

**Critical rules**:
- Rate sign: **NEGATIVE** = extraction. Positive = injection (wrong for ET).
- Rate units: `DATA_UNITS m^3/sec` — for a 1m×1m column, rate [m³/s] = ET [m/s]
- `VOLUME` keyword: required; tells PFLOTRAN to scale by region volume
- Root-zone depth selection (see dt_020 for crash thresholds):
  - Alpine meadow (CN-HaM type): 1.0 m
  - Subtropical/temperate forest: 1.5–2.0 m (never < 1.0 m if dry spells > 10 days)

```python
# Python: build time-varying ET source/sink for PFLOTRAN deck
ROOT_ZONE_DEPTH = 1.5   # m — adjust by site type (see dt_020)
rz_z_bot = COL_DEPTH - ROOT_ZONE_DEPTH   # z at bottom of root zone

et_entries = []
for r in records:
    et_ms = max(0.0, r["le_wm2"] * 86400.0 / 2.45e6) / (1000.0 * 86400.0)
    et_entries.append(f"    {r['day_offset']}.  {-et_ms:.6e}")   # NEGATIVE
et_list_block = "\n".join(et_entries)
```

```
! In PFLOTRAN input deck:
REGION root_zone
  COORDINATES
    0.d0 0.d0 {rz_z_bot}d0
    1.d0 1.d0 {COL_DEPTH}d0
  /
END

FLOW_CONDITION et_extraction
  TYPE
    RATE scaled_volumetric_rate VOLUME
  /
  RATE LIST
    TIME_UNITS d
    DATA_UNITS m^3/sec
    0.   -5.556e-09    ! day 0: ET = 0.48 mm/d → -0.48/(1000*86400)
    1.   -8.102e-09    ! day 1: ET = 0.70 mm/d
    ...
  /
END

SOURCE_SINK et_sink
  FLOW_CONDITION et_extraction
  REGION root_zone
END
```

**Separation of P and ET at top BC** (prevents crash from P-ET negative flux):

```python
# CORRECT: P-only at top BC, ET separately as root-zone sink
net_ms = max(0.0, p_mm) / (1000.0 * 86400.0)   # top BC: always ≥ 0
et_ms  = et_mm / (1000.0 * 86400.0)             # sink: always ≥ 0 before negation
```

Do NOT use P-ET as the top BC — on dry days (P=0, ET>0), the negative Neumann
flux pulls water upward through the top face and rapidly depletes the 5-cm top cell.

## Verification

1. Recharge values in range 1e-11 to 1e-7 m/s (roughly 0.3 to 3000 mm/yr)
2. River pressure > atmospheric (101325 Pa) for submerged cells
3. Pumping rates are negative (extraction) or positive (injection)
4. Time series is monotonically increasing in time
5. No gaps in time series (PFLOTRAN interpolates linearly)
6. Total recharge volume ≈ expected annual precipitation × infiltration fraction

## Traps

| Trap ID | Error | Symptom |
|---|---|---|
| dt_002 | Recharge in mm/yr not m/s | Domain floods or dries instantly |
| dt_003 | Pressure in atm not Pa | No flow (pressure difference ~0) |
| dt_010 | Time in years not seconds | Boundary condition applied at wrong time |
| dt_004 | K_conductor in m/day not m/s | Coupled flow 86400x too fast |

## Example

Bengbu Basin annual recharge (~120 mm/yr = 3.8e-9 m/s):

```
FLOW_CONDITION steady_recharge
  TYPE
    LIQUID_FLUX NEUMANN
  /
  LIQUID_FLUX 3.8d-9   ! 120 mm/yr in m/s
END

BOUNDARY_CONDITION top_bc
  FLOW_CONDITION steady_recharge
  REGION top
END
```
