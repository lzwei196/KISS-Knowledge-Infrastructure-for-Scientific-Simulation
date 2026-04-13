# Stage 1: Reservoir Parameter Conversion

## Purpose

Convert raw site characterization data into GEOPHIRES-compatible reservoir parameters
with correct units. This stage catches the most common unit conversion errors that cause
unrealistic simulation results.

## Inputs

| Input | Source Format | GEOPHIRES Format |
|-------|--------------|------------------|
| Depth | meters (common) | **km** |
| Gradient | °C/m (field measurements) | **°C/km** |
| Flow rate | m³/s or L/s (pump specs) | **kg/s** |
| Well diameter | cm or m (drilling specs) | **inches** |
| Heat capacity | kJ/kg/K (literature) | **J/kg/K** |
| Density | g/cm³ (lab measurements) | **kg/m³** |
| Conductivity | mW/m/K (lab measurements) | **W/m/K** |

## Outputs

- `reservoir_params.txt`: GEOPHIRES-formatted parameter file
- Conversion log with all unit transformations applied

## Procedure

1. **Read reservoir config JSON** containing site data with explicit source units.

2. **Apply unit conversions** using `convert_reservoir_params.py`:
   ```bash
   python convert_reservoir_params.py --config reservoir_config.json --output reservoir_params.txt
   ```

3. **Validate converted values** against physical bounds:
   - Depth: 0.1–15 km
   - Gradient: 5–200 °C/km
   - Flow rate: 1–500 kg/s
   - Well diameter: 1–20 inches

4. **Handle multi-segment gradients** if the site has layered geology:
   ```json
   {
       "number_of_segments": 3,
       "gradient1_degC_per_km": 42.7,
       "gradient2_degC_per_km": 35.0,
       "gradient3_degC_per_km": 55.0
   }
   ```

5. **Set fracture parameters** (for Model 1 or 3):
   - Fracture Shape: 1=circular, 2=elliptical, 3=rectangular, 4=square
   - Number of Fractures: Typically 5–50 for EGS
   - Fracture Height/Width: Typically 100–1000 m

## Verification

- Check that converted depth × gradient gives expected bottom-hole temperature
- Verify flow rate in kg/s: for water at 100°C, 1 L/s ≈ 0.958 kg/s
- Verify well diameter: 7 inches ≈ 17.8 cm ≈ 0.178 m

## Traps

| Trap | Factor | Detection | Impact |
|------|--------|-----------|--------|
| Depth in meters | ÷1000 | Depth > 15 | Astronomical temperature |
| Gradient in °C/m | ×1000 | Gradient < 1 | Near-zero temperature |
| Flow in m³/s not kg/s | ×density | Flow < 0.1 or > 500 | Wrong power output |
| Diameter in cm not inches | ÷2.54 | Diameter > 20 | Pressure drop errors |
| Heat capacity in kJ not J | ×1000 | Cp < 100 | Wrong thermal drawdown |
| Density in g/cm³ not kg/m³ | ×1000 | Density < 10 | Volume calculation errors |

## Example

Input config:
```json
{
    "reservoir_model": 1,
    "depth_m": 3000,
    "gradient_degC_per_m": 0.05,
    "flow_rate_L_per_s": 57.5,
    "production_well_diameter_cm": 17.78,
    "heat_capacity_kJ_per_kgK": 1.0,
    "density_g_per_cm3": 2.7
}
```

Output (reservoir_params.txt):
```
Reservoir Model,1,
Reservoir Depth,3.0,                        ---[km]
Gradient 1,50.0,                            ---[degC/km]
Production Flow Rate per Well,55.1,         ---[kg/s]
Production Well Diameter,7.0,               ---[inch]
Reservoir Heat Capacity,1000.0,             ---[J/kg/K]
Reservoir Density,2700.0,                   ---[kg/m3]
```

All six conversions applied correctly.
