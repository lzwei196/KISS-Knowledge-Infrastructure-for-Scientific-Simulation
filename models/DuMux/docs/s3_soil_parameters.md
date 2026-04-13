# Stage 3: Soil and Aquifer Parameter Conversion

## Purpose

Convert soil and aquifer properties from field measurements, soil databases (HWSD, ROSETTA), or literature values into DuMux-compatible spatial parameter values with correct SI units.

## Inputs

| Input | Format | Source | Unit |
|-------|--------|--------|------|
| Hydraulic conductivity | scalar or field | Pump tests, HWSD, ROSETTA | m/s, cm/day, or darcy |
| Porosity | scalar or field | Lab tests, literature | fraction or % |
| van Genuchten α | scalar | ROSETTA, lab | 1/cm H₂O |
| van Genuchten n | scalar | ROSETTA, lab | dimensionless |
| Residual saturation | scalar | Lab, ROSETTA | fraction |
| Soil texture class | string | USDA classification | - |

## Outputs

| Output | Format | Consumed by | Unit |
|--------|--------|-------------|------|
| Intrinsic permeability | scalar/field | DuMux `[SpatialParams]` | m² |
| Porosity | scalar/field | DuMux `[SpatialParams]` | fraction [-] |
| vG α | scalar | DuMux `[SpatialParams]` | 1/Pa |
| vG n | scalar | DuMux `[SpatialParams]` | dimensionless |
| DuMux .input snippet | text | params.input | - |

## Procedure

### Step 1: Identify soil/aquifer type

Common aquifer types and typical properties:

| Material | K_h [m/s] | K [m²] | φ [-] | vG α [1/cm] | vG n |
|----------|-----------|---------|-------|-------------|------|
| Gravel | 1e-2–1 | 1e-9–1e-7 | 0.25–0.40 | 0.5 | 3.0 |
| Coarse sand | 1e-4–1e-2 | 1e-11–1e-9 | 0.30–0.45 | 0.145 | 2.68 |
| Fine sand | 1e-5–1e-4 | 1e-12–1e-11 | 0.35–0.45 | 0.075 | 1.89 |
| Silt | 1e-7–1e-5 | 1e-14–1e-12 | 0.35–0.50 | 0.016 | 1.37 |
| Clay | 1e-10–1e-7 | 1e-17–1e-14 | 0.35–0.60 | 0.008 | 1.09 |
| Fractured rock | 1e-8–1e-4 | 1e-15–1e-11 | 0.01–0.10 | 0.001 | 1.5 |
| Sandstone | 1e-8–1e-5 | 1e-15–1e-12 | 0.05–0.30 | 0.01 | 1.5 |
| Limestone | 1e-7–1e-4 | 1e-14–1e-11 | 0.01–0.20 | 0.005 | 1.3 |

### Step 2: Convert hydraulic conductivity to intrinsic permeability

**THE most critical conversion in DuMux groundwater modeling.**

```
K [m²] = K_h [m/s] × μ / (ρ × g)
```

Where:
- μ = 1.002×10⁻³ Pa·s (water viscosity at 20°C)
- ρ = 1000 kg/m³ (water density)
- g = 9.81 m/s²

```
K [m²] = K_h [m/s] × 1.002e-3 / (1000 × 9.81)
       = K_h [m/s] × 1.0214e-7
```

**From cm/day**:
```
K [m²] = K_h [cm/day] / (100 × 86400) × 1.0214e-7
       = K_h [cm/day] × 1.183e-14
```

**From darcy**:
```
K [m²] = K_h [darcy] × 9.869e-13
```

### Step 3: Convert van Genuchten α

```
α [1/Pa] = α [1/cm H₂O] / 98.0665
```

Where 98.0665 Pa = 1 cm of water head (= ρ·g/100).

### Step 4: Convert porosity

If given as percentage, divide by 100:
```
φ [-] = φ [%] / 100
```

### Step 5: Write DuMux parameter section

```ini
[SpatialParams]
Permeability = 1.0214e-11     # [m²] (from K_h = 1e-4 m/s, fine sand)
Porosity = 0.35               # [-]
VanGenuchtenAlpha = 7.647e-4  # [1/Pa] (from 0.075 1/cm)
VanGenuchtenN = 1.89          # [-]
Swr = 0.15                    # [-] residual water saturation
```

### Step 6: For heterogeneous fields

If permeability varies spatially, define zones in the C++ SpatialParams class:
```cpp
Scalar permeabilityAtPos(const GlobalPosition& pos) const {
    if (isInZone(pos, zone1_bounds))
        return zone1_perm;  // m²
    return background_perm;  // m²
}
```

Or read from an external field file.

## Verification

1. **Permeability magnitude**: For typical aquifers, K should be 1e-15 to 1e-8 m².
   - If K > 1e-7: probably used K_h directly without conversion
   - If K < 1e-20: probably near-impermeable, double-check
2. **Porosity range**: Must be 0 < φ < 1. If φ > 1, input was in percent.
3. **vG α range**: In 1/Pa, typical values are 1e-5 to 1e-2.
   - If α > 0.1: probably still in 1/cm, forgot to divide by 98.07
4. **vG n range**: Must be > 1. Typical 1.1–5.0. If n < 1, the capillary pressure law is undefined.

## Traps

### TRAP: Using K_h as permeability (off by ~1e7)
The most common DuMux groundwater error. K_h [m/s] values (e.g., 1e-4) are ~1e7 times larger than intrinsic permeability K [m²] (e.g., 1e-11).

**Symptom**: Flow velocities are enormous, heads go to extreme values, Newton solver diverges.
**Fix**: Apply the conversion K = K_h × μ/(ρg).

### TRAP: vG α in wrong units (off by ~100×)
ROSETTA gives α in 1/cm. DuMux needs 1/Pa. Missing the conversion shifts capillary pressure by ~100×, completely changing the soil moisture retention curve.

**Symptom**: Unsaturated zone behavior is wrong — either holds too much or too little water.
**Fix**: Divide α by 98.0665.

### TRAP: Zero porosity crashes the simulation
Porosity = 0 makes the storage term zero, causing division by zero in the time-stepping scheme. DuMux may crash or produce NaN.

**Symptom**: NaN in solution vector, segfault.
**Fix**: Always ensure porosity > 0 (minimum ~0.001 for near-impermeable materials).

### TRAP: Temperature dependence of viscosity
At T ≠ 20°C, water viscosity changes significantly:
- 5°C: μ = 1.519e-3 Pa·s (50% higher than 20°C)
- 30°C: μ = 0.798e-3 Pa·s (20% lower)

Using the 20°C value for K→permeability conversion introduces error. For non-isothermal simulations, DuMux handles this internally — just provide correct permeability.

## Example

```bash
# Convert from USDA texture class
python tools/convert_soil_to_dumux.py \
    --source texture --texture "sandy_loam" \
    --output sandy_loam_params.json

# Convert from CSV with K_h in cm/day
python tools/convert_soil_to_dumux.py \
    --input field_data.csv --source csv \
    --kh_unit cm_per_day \
    --output aquifer_params.json
```

Output JSON includes DuMux .input snippet ready to paste into params.input.
