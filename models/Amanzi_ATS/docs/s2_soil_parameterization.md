# S2: Soil / Material Parameterization

## Purpose

Convert soil properties from global databases (HWSD, SoilGrids) or literature into Amanzi-compatible material parameters. The critical conversion is from hydraulic conductivity (K, m/s) to intrinsic permeability (k, m²), and from van Genuchten parameters in common units (α in 1/cm) to Amanzi's SI units (α in 1/Pa).

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| USDA texture class | HWSD, SoilGrids | String | e.g., "sandy loam" |
| Saturated hydraulic conductivity | HWSD, lab tests | Numeric | cm/day, m/s, cm/hr |
| Porosity | HWSD, SoilGrids | Numeric | dimensionless (0-1) |
| van Genuchten α | Rosetta, literature | Numeric | 1/cm (common), 1/m, 1/Pa |
| van Genuchten n | Rosetta, literature | Numeric | dimensionless (>1) |
| Residual water content θ_r | Literature | Numeric | dimensionless (0-1) |
| Sorption Kd | Literature | Numeric | mL/g |
| Dispersivity | Literature | Numeric | cm or m |

## Outputs

| Output | Format | Units | Destination |
|--------|--------|-------|-------------|
| Intrinsic permeability | JSON / XML | m² | `<materials>` permeability |
| Porosity | JSON / XML | dimensionless | `<materials>` porosity |
| van Genuchten α | JSON / XML | 1/Pa | `<materials>` capillary_pressure |
| van Genuchten m (= 1-1/n) | JSON / XML | dimensionless | `<materials>` capillary_pressure |
| Residual saturation S_r | JSON / XML | dimensionless | `<materials>` capillary_pressure |
| Sorption Kd | JSON / XML | m³/kg | `<chemistry>` sorption |

## Procedure

1. **Determine texture class** from HWSD or user input.

2. **Look up pedotransfer parameters** (Carsel & Parrish 1988 or Rosetta):
   - Each USDA texture class maps to α, n, θ_r, θ_s, K_sat.

3. **Convert hydraulic conductivity to intrinsic permeability**:
   ```
   K [m/s] = K [cm/day] / 100 / 86400
   k [m²] = K [m/s] × μ / (ρ × g)
   ```
   Where μ = 1.002e-3 Pa·s, ρ = 998.2 kg/m³, g = 9.80665 m/s².
   Shortcut: k ≈ K [m/s] × 1.02e-7.

4. **Convert van Genuchten α**:
   ```
   α [1/m] = α [1/cm] × 100
   α [1/Pa] = α [1/m] / (ρ × g)
   ```
   Shortcut: α [1/Pa] = α [1/cm] / 980665.

5. **Compute van Genuchten m**: m = 1 - 1/n.

6. **Convert residual water content to residual saturation**:
   ```
   S_r = θ_r / θ_s  (= θ_r / porosity)
   ```

7. **Convert Kd** (if sorption modeling):
   ```
   Kd [m³/kg] = Kd [mL/g] × 0.001
   ```

## Verification

| Parameter | Typical Range | Red Flag |
|-----------|--------------|----------|
| Permeability k | 1e-16 – 1e-9 m² | > 1e-6 (used K not k) |
| α (1/Pa) | 1e-6 – 1e-2 | > 0.1 (used 1/cm directly) |
| n | 1.05 – 3.0 | < 1.0 (invalid) |
| Porosity | 0.01 – 0.6 | > 0.8 or < 0.01 |
| S_r | 0.01 – 0.4 | > 0.9 (nearly saturated) |

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| **dt_001** | K (m/s) used as k (m²) | 7 orders too permeable; instant drainage |
| **dt_004** | α in 1/cm used where 1/Pa expected | Soil drains instantly; no capillary retention |
| **dt_012** | Kd in mL/g used where m³/kg expected | 1000× too much sorption |
| **dt_015** | S_r ≥ 1.0 | Negative effective saturation; solver crash |

## Example

```bash
python ki/tools/convert_soil_to_amanzi.py \
  --texture "sandy loam" \
  --output soil_params.json

# Output:
#   Permeability: 1.25e-12 m²
#   α (vG): 7.65e-05 1/Pa
#   n (vG): 1.89
#   Porosity: 0.410
```

### Typical Values by Texture Class

| Texture | k (m²) | α (1/Pa) | n | θ_s | θ_r |
|---------|--------|----------|---|-----|-----|
| Sand | 8.42e-12 | 1.48e-4 | 2.68 | 0.43 | 0.045 |
| Sandy loam | 1.25e-12 | 7.65e-5 | 1.89 | 0.41 | 0.065 |
| Loam | 2.95e-13 | 3.67e-5 | 1.56 | 0.43 | 0.078 |
| Clay | 5.67e-14 | 8.16e-6 | 1.09 | 0.38 | 0.068 |

### XML Usage

```xml
<materials>
  <material name="Sandy_Loam">
    <assigned_regions>Subsurface</assigned_regions>
    <mechanical_properties>
      <porosity model="constant" value="0.41"/>
    </mechanical_properties>
    <permeability x="1.25e-12" y="1.25e-12" z="1.25e-12"/>
    <cap_pressure model="van_genuchten">
      <parameters alpha="7.65e-05" m="0.4709" sr="0.1585"/>
    </cap_pressure>
  </material>
</materials>
```
