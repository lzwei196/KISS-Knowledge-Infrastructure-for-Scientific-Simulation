# Stage 2: Forcing and Input Data — Boundary Conditions with Unit Conversions

## Purpose

Convert external environmental data (meteorological, hydrological, geological) into OGS-compatible boundary conditions. This stage handles the most dangerous class of errors: **unit conversion traps** that produce silently wrong results.

## Inputs

- **Meteorological data**: Precipitation, temperature, evapotranspiration
- **Hydrological data**: River stage, well pumping rates, recharge estimates
- **Pressure data**: Hydraulic head observations, piezometer readings

## Outputs

- Time-dependent BC values in OGS format (CSV with time in seconds, values in SI)
- Spatially varying parameter fields (VTU files with node/cell data)

## Procedure

### Step 1: Identify boundary condition types

| BC Type | OGS XML | Example Application |
|---------|---------|---------------------|
| Dirichlet | `<type>Dirichlet</type>` | Fixed head at river boundary |
| Neumann | `<type>Neumann</type>` | Recharge flux at ground surface |
| Robin | `<type>Robin</type>` | River-aquifer exchange |
| Nodal source | `<source_term>` | Well pumping/injection |

### Step 2: Apply unit conversions

**THIS IS THE MOST CRITICAL STEP.** OGS uses strict SI. Every value must be in:
- Pressure: **Pa** (not kPa, not bar, not m of water head)
- Temperature: **K** (not °C)
- Length: **m** (not cm, not km)
- Time: **s** (not days, not hours)
- Flow rate: **m³/s** (not L/s, not m³/day)
- Flux: **m/s** (not mm/day)
- Permeability: **m²** (not Darcy, not m/s)

**Common conversion formulas**:

```python
# Hydraulic head (m) to pressure (Pa)
pressure_Pa = head_m * 998.2 * 9.81  # ≈ head × 9792

# Temperature (°C) to Kelvin
temp_K = temp_C + 273.15

# Recharge (mm/day) to flux (m/s)
flux_m_s = recharge_mm_day / (1000.0 * 86400.0)  # ÷ 86,400,000

# Precipitation (mm/day) to m/s
precip_m_s = precip_mm_day / (1000.0 * 86400.0)

# Well rate (L/s) to m³/s
rate_m3_s = rate_L_s / 1000.0

# Well rate (m³/day) to m³/s
rate_m3_s = rate_m3_day / 86400.0

# Hydraulic conductivity (m/s) to intrinsic permeability (m²)
perm_m2 = K_m_s * 1.002e-3 / (998.2 * 9.81)  # ≈ K × 1.02e-7

# Permeability (Darcy) to m²
perm_m2 = perm_darcy * 9.869e-13

# van Genuchten α (1/cm) to entry pressure (Pa)
alpha_per_m = alpha_per_cm * 100  # Convert to 1/m first!
entry_pressure_Pa = 998.2 * 9.81 / alpha_per_m
```

### Step 3: Format time series for OGS

OGS reads time-dependent BCs from `<curves>` blocks in the project file:

```xml
<curves>
  <curve>
    <name>recharge_curve</name>
    <coords>0 86400 172800 259200</coords>     <!-- time in seconds -->
    <values>1.16e-8 2.31e-8 0.0 5.79e-9</values>  <!-- flux in m/s -->
  </curve>
</curves>
```

Alternative: Use `CurveScaledParameter` with external CSV file.

### Step 4: Validate converted values

Use the tool: `python tools/convert_forcing_to_ogs.py`

**Sanity check ranges** (after conversion to SI):

| Variable | Min | Max | If outside → |
|----------|-----|-----|-------------|
| Recharge (m/s) | 0 | 1e-6 | Unit error likely |
| Pressure (Pa) | -1e6 | 1e8 | Check head conversion |
| Temperature (K) | 250 | 350 | Check °C→K |
| Pumping rate (m³/s) | 0 | 0.1 | Check L/s conversion |

## Verification

- [ ] All pressures in Pa (not kPa, not m head)
- [ ] All temperatures in K (not °C) — values should be > 200
- [ ] All times in seconds (not days)
- [ ] Recharge flux < 1e-6 m/s for typical climates
- [ ] No negative precipitation/recharge values
- [ ] Time series spans full simulation period

## Traps

| Trap ID | Description | Factor | Symptom |
|---------|-------------|--------|---------|
| dt_001 | Pressure in kPa not Pa | 1000× low | Head drops unrealistically |
| dt_002 | Temperature in °C not K | ~253 K low | Wrong density/viscosity |
| dt_004 | Time in days not seconds | 86400× short | Simulation ends instantly |
| dt_013 | Recharge in mm/day not m/s | 86.4M× high | Domain floods |
| dt_015 | Precip mm/day missing /86400 | 86400× high | Massive over-recharge |

## Example

Converting daily recharge data from a weather station:

```bash
# Input: recharge.csv with columns [date, recharge_mm_day]
# Output: OGS-compatible recharge in m/s with time in seconds

python tools/convert_forcing_to_ogs.py \
  --source recharge.csv --variable recharge \
  --source_unit mm/day --target_unit m/s \
  --start_date 2000-01-01 --end_date 2010-12-31 \
  --output recharge_ogs.csv

# Verify: max value should be ~1e-7 for temperate climate
head -5 recharge_ogs.csv
# time_s,recharge
# 0,1.157e-08
# 86400,2.315e-08
```
