# Stage 0: Site Characterization

## Purpose

Define the geothermal site properties and project goals before running GEOPHIRES.
This manual stage establishes the reservoir type, depth, thermal gradient, end-use option,
and economic framework. All subsequent stages depend on decisions made here.

## Inputs

| Parameter | Description | Typical Range | Unit |
|-----------|-------------|---------------|------|
| Reservoir type | EGS, hydrothermal, CLGS, or SUTRA | - | Enum (0-8) |
| Reservoir depth | Depth to top of reservoir | 0.5–10 | km |
| Geothermal gradient | Temperature increase with depth | 20–100 | °C/km |
| Surface temperature | Mean annual surface temperature | -10 to 30 | °C |
| Rock density | Reservoir rock bulk density | 2000–3500 | kg/m³ |
| Thermal conductivity | Reservoir rock thermal conductivity | 1.0–5.0 | W/m/K |
| Heat capacity | Reservoir rock specific heat | 700–1200 | J/kg/K |
| End-use option | Electricity, heat, or cogeneration | 1, 2, 31-52 | Enum |
| Economic model | FCR, Standard, BICYCLE, CLGS, or SAM | 1–5 | Enum |

## Outputs

- Site parameter JSON or reservoir config file for Stage 1
- Economic assumptions JSON for Stage 2
- Clear specification of reservoir model and end-use

## Procedure

1. **Select reservoir type** based on geological setting:
   - Known fracture zone → Model 1 (Multiple Parallel Fractures)
   - Porous sedimentary → Model 2 (Linear Heat Sweep)
   - Single major fracture → Model 3 (Single Fracture)
   - Screening/unknown → Model 4 (Percentage Thermal Drawdown)
   - Measured production data → Model 5 (User-Provided)
   - Closed-loop design → Model 8 (SBT)

2. **Determine depth and gradient** from well logs, regional data, or literature.
   For multi-segment gradients, specify up to 4 gradient/thickness pairs.

3. **Set rock properties** from core samples, literature, or regional databases:
   - Granite: ρ=2650 kg/m³, k=2.5–3.5 W/m/K, Cp=790 J/kg/K
   - Sandstone: ρ=2300 kg/m³, k=1.5–4.0 W/m/K, Cp=920 J/kg/K
   - Basalt: ρ=2900 kg/m³, k=1.5–2.5 W/m/K, Cp=840 J/kg/K

4. **Choose end-use** based on resource temperature and market:
   - T > 150°C → Electricity (ORC or flash)
   - 80°C < T < 150°C → Direct-use heat or cogeneration
   - T < 80°C → Heat pump assisted

5. **Select economic model** based on analysis requirements:
   - Quick estimate → FCR (Model 1)
   - Standard analysis → Standard (Model 2)
   - Detailed finance → BICYCLE (Model 3) or SAM (Model 5)

## Verification

- Bottom-hole temperature = Surface temperature + Depth × Gradient
- Verify temperature is consistent with chosen end-use and plant type
- Check that rock properties are consistent with known geology

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Depth in meters instead of km | Extreme temperatures, impossible costs | Divide by 1000 |
| Gradient in °C/m instead of °C/km | Near-zero temperature | Multiply by 1000 |
| Wrong reservoir model for geology | Unrealistic drawdown profile | Re-examine site geology |
| End-use/plant type mismatch | Zero or negative power output | Match plant type to resource temp |

## Example

For a 3 km deep EGS site with 50°C/km gradient and granite rock:

```json
{
    "reservoir_model": 1,
    "depth_km": 3.0,
    "gradient_degC_per_km": 50.0,
    "surface_temperature_degC": 15.0,
    "density_kg_per_m3": 2650,
    "thermal_conductivity_W_per_mK": 3.0,
    "heat_capacity_J_per_kgK": 790,
    "maximum_temperature_degC": 400,
    "end_use_option": "electricity",
    "economic_model": 1
}
```

Expected bottom-hole temperature: 15 + 3.0 × 50 = 165°C → suitable for ORC electricity.
