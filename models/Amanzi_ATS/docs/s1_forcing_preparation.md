# S1: Forcing / Recharge Data Preparation

## Purpose

Convert global meteorological and recharge data into Amanzi-compatible boundary condition parameters. Amanzi uses SI units (kg/m²/s for mass flux, Pa for pressure, K for temperature), so all external data sources require explicit unit conversion.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Precipitation | ERA5, CMFD, MSWX | NetCDF, CSV | mm/hr, mm/3hr, mm/day |
| Recharge rate | Literature, water balance | Scalar or time series | mm/yr, cm/yr |
| Temperature | ERA5, CMFD | NetCDF, CSV | °C or K |
| Pressure head | Observations | Time series | m (hydraulic head) |

## Outputs

| Output | Format | Units | Destination |
|--------|--------|-------|-------------|
| Recharge flux | JSON / XML snippet | kg/m²/s | `<boundary_conditions>` mass_flux |
| Temperature | JSON / XML snippet | K | `<initial_conditions>` or `<boundary_conditions>` |
| Pressure | JSON / XML snippet | Pa | `<boundary_conditions>` uniform_pressure |
| Time array | JSON | seconds | `<execution_control>` start/end |

## Procedure

1. **Identify recharge source**: Determine whether using constant recharge (typical for steady-state) or time-varying (transient from climate data).

2. **Convert precipitation to recharge flux**:
   - mm/yr → kg/m²/s: `R_si = R_mm_yr × ρ_w / (1000 × 3.156e7)`
   - cm/yr → kg/m²/s: `R_si = R_cm_yr × ρ_w / (100 × 3.156e7)`
   - mm/hr → kg/m²/s: `R_si = R_mm_hr × ρ_w / (1000 × 3600)`
   - Where ρ_w = 998.2 kg/m³

3. **Convert temperature** (if energy equation is active):
   - °C → K: `T_K = T_C + 273.15`

4. **Convert pressure head to pressure**:
   - Head (m) → Pa: `P = P_atm + ρ_w × g × (h - z_ref)`
   - P_atm = 101325 Pa, g = 9.80665 m/s²

5. **Convert time units**:
   - years → seconds: `t_s = t_yr × 3.156e7`
   - days → seconds: `t_s = t_d × 86400`

6. **Write output** in JSON or XML format compatible with Amanzi input assembler.

## Verification

- Recharge flux should be O(1e-8) kg/m²/s for typical climates (100-1000 mm/yr).
- Max recharge: ~1.6e-5 kg/m²/s (= 5000 mm/yr, tropical extreme).
- Temperature in Kelvin: 250-320 K range for surface conditions.
- Pressure at 10 m depth: ~101325 + 9806.65×10 ≈ 199392 Pa.

## Traps

| Trap | Description | Detection |
|------|-------------|-----------|
| **dt_001** | Using K (m/s) where k (m²) is needed | Permeability > 1e-6 |
| **dt_011** | Recharge not converted from cm/yr to SI | Flux > 1e-4 kg/m²/s |
| **dt_006** | Time units mixed (years entered as seconds) | Simulation duration unrealistic |

## Example

```bash
# Convert 300 mm/yr constant recharge for a 10-year simulation
python ki/tools/convert_forcing_to_amanzi.py \
  --recharge_mm_yr 300 \
  --start_year 2000 --end_year 2010 \
  --region "Top Surface" \
  --output forcing_params.json

# Result: recharge_kg_m2_s = 9.49e-6 (≈300 mm/yr)
```

### XML Usage

```xml
<boundary_conditions>
  <boundary_condition name="Recharge">
    <assigned_regions>Top Surface</assigned_regions>
    <liquid_phase name="water">
      <liquid_component name="water">
        <inward_mass_flux function="constant" start="0.0" value="9.49e-6"/>
      </liquid_component>
    </liquid_phase>
  </boundary_condition>
</boundary_conditions>
```
