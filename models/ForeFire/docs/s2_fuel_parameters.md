# Stage 2: Fuel Parameter Configuration

## Purpose

Create the fuel properties table (`fuels.csv`) that defines combustion characteristics for each fuel type. This is the most model-sensitive stage — unit errors here produce silent ROS calculation failures.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Fuel model database | Literature/database | Anderson 13, Scott & Burgan 40, Prometheus | Standard fuel model parameters |
| Custom fuel measurements | CSV | Field data | Site-specific fuel characteristics |
| Propagation model choice | String | User | Determines required columns and unit system |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `fuels.csv` | Semicolon-delimited CSV | Fuel properties indexed by type |

## Procedure

1. **Select propagation model**: This determines the fuel parameter format.
   - `Rothermel` / `Balbi2020`: SI units (kg/m³, 1/m, m, kg/m², J/kg)
   - `RothermelAndrews2018`: Imperial units (tons/acre, ft, 1/ft, lb/ft³, BTU/lb)
   - `Farsite`: NFFL/FBFM standard (moisture class loads)

2. **Prepare fuel table**: Map each fuel type index to its parameters.
   - Index 0 should be non-burnable (fuel depth `e = 0` → ROS = 0)
   - Indices 1-N map to vegetation types in the fuel raster

3. **Unit conversions** (if using literature values in wrong units):
   - For Rothermel/Balbi from Imperial:
     - Density: lb/ft³ × 16.0185 = kg/m³
     - SAV: 1/ft × 3.28084 = 1/m
     - Depth: ft ÷ 3.28084 = m
     - Loading: lb/ft² × 4.88243 = kg/m²
     - Heat: BTU/lb × 2326 = J/kg

4. **Write fuels.csv**: Semicolon-delimited, with header row matching model expectations.

5. **Validate**: Check all values are physically reasonable.

## Verification

### For Rothermel/Balbi fuels.csv:
- `Rhod` (dead fuel density): 200-900 kg/m³ typical
- `sd` (SAV ratio): 2000-12000 1/m typical
- `e` (fuel depth): 0-3 m typical
- `Sigmad` (fuel load): 0.1-5 kg/m² typical
- `DeltaH` (heat of combustion): 15,000,000-21,000,000 J/kg typical
- `me` (moisture of extinction): 0.1-0.5 (fraction, NOT percentage)
- `Md` (dead fuel moisture): 0.03-0.40 (fraction)
- `Ta` (ambient temperature): 280-320 K (must be Kelvin, NOT Celsius)
- `Ti` (ignition temperature): 500-700 K

### For RothermelAndrews2018:
- `fl1h_tac` (1-hr fuel load): 0.1-10 US tons/acre
- `fd_ft` (fuel depth): 0.1-10 ft
- `SAVcar_ftinv` (SAV): 100-3500 1/ft
- `Dme_pc` (moisture of extinction): 12-40 (percentage, NOT fraction)

## Traps

### Trap 1: Double unit conversion for Rothermel
**Symptom**: ROS is orders of magnitude off (too fast or too slow).
**Cause**: The Rothermel model code internally converts SI → Imperial for calculation. If fuels.csv is already in Imperial, values get double-converted.
**Fix**: fuels.csv must be in SI for Rothermel/Balbi. The code handles conversion.

### Trap 2: Moisture of extinction units
**Symptom**: Fire doesn't spread even in dry conditions (Rothermel), or spreads too easily (Andrews).
**Cause**: `me` for Rothermel is fraction (0.3 = 30%), but `Dme_pc` for Andrews is percentage (30).
**Fix**: Check which model you're using and use the correct unit convention.

### Trap 3: Temperature in Celsius instead of Kelvin
**Symptom**: Negative ignition energy, numerical errors, or no spread.
**Cause**: `Ta` (ambient) and `Ti` (ignition) must be in Kelvin.
**Fix**: Add 273.15 to convert from Celsius.

### Trap 4: Non-burnable fuel with e > 0
**Symptom**: Water, roads, or urban areas catch fire.
**Cause**: Non-burnable fuel types have non-zero fuel depth.
**Fix**: Set `e = 0` for fuel index 0 (and any non-burnable type).

### Trap 5: Semicolon vs comma delimiter
**Symptom**: ForeFire crashes or loads wrong values from fuels.csv.
**Cause**: ForeFire expects semicolons (`;`), not commas.
**Fix**: Always use semicolon as delimiter: `Index;Rhod;Rhol;...`

## Example

```bash
# Generate Anderson 13 fuel table for Rothermel model
python tools/convert_fuel_params.py \
    --model rothermel \
    --source anderson13 \
    --output fuels.csv

# Verify header
head -1 fuels.csv
# Expected: Index;Rhod;Rhol;Md;Ml;sd;sl;e;Sigmad;Sigmal;stoch;RhoA;Ta;Tau0;Deltah;DeltaH;Cp;Cpa;Ti;X0;r00;Blai;me
```

Then in the .ff script:
```
setParameter[fuelsTableFile=fuels.csv]
setParameter[propagationModel=Rothermel]
```
