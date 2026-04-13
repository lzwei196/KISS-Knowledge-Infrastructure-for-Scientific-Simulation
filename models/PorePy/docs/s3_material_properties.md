# S3: Material Properties Configuration

## Purpose

Configure solid (rock) and fluid material properties for PorePy simulations. All
properties must be specified in SI units. This stage maps external data sources
(lab measurements, literature values, HWSD soil database) to PorePy's
`SolidConstants` and `FluidComponent` objects.

## Inputs

| Input                    | Type    | Unit        | Description                      |
|--------------------------|---------|-------------|----------------------------------|
| Rock density             | float   | kg/m³       | Bulk density of solid matrix     |
| Porosity                 | float   | — (0–1)     | Void fraction                    |
| Permeability             | float   | m²          | Intrinsic permeability           |
| Biot coefficient         | float   | — (0–1]     | Poroelastic coupling parameter   |
| Shear modulus            | float   | Pa          | Elastic shear modulus (G)        |
| Lame lambda              | float   | Pa          | First Lame parameter (λ)        |
| Specific heat capacity   | float   | J/(kg·K)    | Solid heat capacity              |
| Thermal conductivity     | float   | W/(m·K)     | Solid thermal conductivity       |
| Friction coefficient     | float   | —           | Coulomb friction for fractures   |
| Fluid density            | float   | kg/m³       | Fluid mass density               |
| Fluid viscosity          | float   | Pa·s        | Dynamic viscosity                |
| Fluid compressibility    | float   | 1/Pa        | Isentropic compressibility       |
| Thermal expansion        | float   | 1/K         | Volumetric thermal expansion     |

## Outputs

| Output              | Type                  | Description                         |
|---------------------|-----------------------|-------------------------------------|
| SolidConstants      | `pp.SolidConstants`   | Rock properties for simulation      |
| FluidComponent      | `pp.FluidComponent`   | Fluid properties for simulation     |
| material_constants  | `dict`                | Combined dict for model_params      |

## Procedure

### Step 1: Choose base rock type

```python
# Option A: Use built-in library values
from porepy.applications.material_values.solid_values import granite
solid = pp.SolidConstants(**granite)

# Option B: Custom values (all SI)
custom_rock = {
    "name": "custom_sandstone",
    "density": 2300.0,           # kg/m³
    "porosity": 0.15,            # fraction
    "permeability": 1e-14,       # m²
    "biot_coefficient": 0.79,    # dimensionless
    "shear_modulus": 6e9,        # Pa
    "lame_lambda": 4e9,          # Pa
    "specific_heat_capacity": 920.0,  # J/(kg·K)
    "thermal_conductivity": 2.3,      # W/(m·K)
    "friction_coefficient": 0.5,
}
solid = pp.SolidConstants(**custom_rock)
```

### Step 2: Configure fluid properties

```python
from porepy.applications.material_values.fluid_values import water
fluid = pp.FluidComponent(**water)

# Or custom fluid
brine = {
    "name": "brine",
    "density": 1050.0,           # kg/m³
    "viscosity": 1.2e-3,         # Pa·s
    "compressibility": 4.0e-10,  # 1/Pa
    "specific_heat_capacity": 3900.0,  # J/(kg·K)
    "thermal_conductivity": 0.62,      # W/(m·K)
    "thermal_expansion": 3.0e-4,       # 1/K
}
fluid = pp.FluidComponent(**brine)
```

### Step 3: Assemble material constants

```python
model_params["material_constants"] = {
    "solid": solid,
    "fluid": fluid,
}
```

### Step 4: Convert from external data (optional)

```bash
# Convert from external JSON with unit annotations
python ki/tools/convert_material_params.py \
    --input lab_measurements.json \
    --rock-type sandstone \
    --output porepy_materials.json
```

## Verification

- Porosity must be 0 < φ ≤ 1 (NOT percentage)
- Biot coefficient must be 0 < α ≤ 1
- Permeability should be 1e-22 to 1e-10 m² for natural rock
- Density should be 1000–3500 kg/m³ for rock, 800–1200 kg/m³ for fluid
- Viscosity should be 1e-4 to 1e-1 Pa·s for common fluids

## Traps

| ID     | Trap                                    | Consequence                               |
|--------|-----------------------------------------|-------------------------------------------|
| dt_001 | Permeability in Darcy (not m²)          | Flow rates 1e12× too large                |
| dt_003 | Viscosity in cP (not Pa·s)              | Darcy velocity 1000× wrong                |
| dt_004 | Density in g/cm³ (not kg/m³)            | Gravity term 1000× wrong                  |
| dt_005 | Modulus in GPa (not Pa)                 | Displacement 1e9× too large               |
| dt_006 | Porosity as percentage (50 not 0.5)     | Mass balance 100× wrong                   |
| dt_009 | Biot coefficient > 1                    | Negative effective stress, divergence      |
| dt_012 | Fracture aperture in mm (not m)         | Transmissivity 1e9× wrong                 |

## Example

```python
import porepy as pp

# Granite matrix with water
granite_vals = {
    "name": "granite",
    "density": 2683.0,
    "porosity": 0.013,
    "permeability": 5e-18,
    "biot_coefficient": 0.47,
    "shear_modulus": 1.485e10,
    "lame_lambda": 7.021e9,
    "specific_heat_capacity": 790.0,
    "thermal_conductivity": 2.5,
    "friction_coefficient": 0.6,
}

water_vals = {
    "name": "water",
    "density": 998.2,
    "viscosity": 1.002e-3,
    "compressibility": 4.559e-10,
    "specific_heat_capacity": 4182.0,
    "thermal_conductivity": 0.5975,
    "thermal_expansion": 2.068e-4,
}

model_params = {
    "material_constants": {
        "solid": pp.SolidConstants(**granite_vals),
        "fluid": pp.FluidComponent(**water_vals),
    },
}
```
