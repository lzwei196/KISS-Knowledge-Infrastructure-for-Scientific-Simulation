# Stage 3: Parameter Setup

## Purpose

Create the `params.dat` file with calibrated or default model parameters.
Map soil and land cover properties to TOPMODEL's parameter space.

## Inputs

| Input | Description |
|-------|-------------|
| Soil data | HWSD or SoilGrids for hydraulic conductivity, porosity |
| Land cover | AVHRR for root zone depth estimates |
| Basin characteristics | Area, mean slope, channel length |
| Prior knowledge | Literature values for similar basins |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| params.dat | TOPMODEL text | 12 parameters on one line |

## Parameter Reference

| # | Name | Unit | Range | Description |
|---|------|------|-------|-------------|
| 1 | szm | m | 0.001–0.1 | Exponential decline of transmissivity with depth |
| 2 | t0 | ln(m/hr) | -1 to 9 | ln(T0): natural log of saturated surface transmissivity. Binary computes szq=exp(t0+log(dt)-TL) (topmodel.c:837-840). NOT linear T0. |
| 3 | td | hr | 1–100 | Unsaturated zone time delay |
| 4 | chv | m/hr | 1000–5000 | Channel flow velocity |
| 5 | rv | m/hr | 500–5000 | Overland flow velocity |
| 6 | srmax | m | 0.001–0.5 | Maximum root zone storage |
| 7 | Q0 | m/hr | 1e-6–1e-3 | Initial subsurface flow |
| 8 | sr0 | m | 0–srmax | Initial root zone deficit |
| 9 | infex | 0/1 | — | Infiltration excess flag (usually 0) |
| 10 | xk0 | m/hr | 0.01–10 | Surface hydraulic conductivity |
| 11 | hf | m | 0.01–0.5 | Wetting front suction (Green-Ampt) |
| 12 | dth | — | 0–1 | Water content change at wetting front |

## Procedure

1. **Estimate szm from soil data**:
   - Related to soil depth and transmissivity profile
   - Sandy soils: szm ~ 0.01–0.03
   - Clay soils: szm ~ 0.03–0.08
   - Use HWSD soil texture class as guide

2. **Estimate t0 from hydraulic conductivity**:
   - T0 = Ksat × soil_depth (approximate), then set t0 = ln(T0)  # binary exponentiates t0
   - Ksat from HWSD or SoilGrids
   - Convert Ksat to m/hr if given in cm/day: × 1/(240)

3. **Estimate srmax from land cover**:
   - Forest: srmax ~ 0.05–0.15 m
   - Cropland: srmax ~ 0.02–0.08 m
   - Grassland: srmax ~ 0.01–0.05 m

4. **Set channel/routing velocities**:
   - chv: typically 1000–5000 m/hr (0.3–1.4 m/s)
   - rv: typically 500–3600 m/hr (0.15–1.0 m/s)

5. **Set initial conditions**:
   - Q0: estimate from observed low flow (convert m³/s to m/hr)
   - sr0: start at 0 (near field capacity) or small value
   - sr0 must be ≤ srmax

6. **Write params.dat**:
   ```
   Basin Name
   {szm}  {t0}  {td}  {chv}  {rv}  {srmax}  {Q0}  {sr0}  {infex}  {xk0}  {hf}  {dth}
   ```

## Verification

- [ ] All parameters are in correct units (meters and hours)
- [ ] sr0 ≤ srmax
- [ ] Q0 > 0 (non-zero initial flow)
- [ ] infex = 0 unless infiltration excess is expected
- [ ] Parameter values are within physically reasonable ranges
- [ ] szm > 0 (zero causes division by zero)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Ksat in cm/day, used as m/hr | t0 off by ~240× | Convert: m/hr = cm/day / 240 |
| srmax = 0 | Division by zero in ET calc | Set srmax > 0.001 |
| sr0 > srmax | Invalid initial state | Ensure sr0 ≤ srmax |
| chv in m/s not m/hr | Routing too slow by 3600× | chv_mhr = chv_ms × 3600 |
| Q0 in m³/s not m/hr | Wrong initial flow | Q0_mhr = Q0_m3s × 3600 / area_m2 |

## Example

```python
# Bengbu basin - reasonable starting parameters
params = {
    'szm': 0.04,      # moderate for mixed soils
    't0': 5.0,        # ln(T0); exp(5)=148 m/hr transmissivity (t0 is LN-scale)
    'td': 30.0,       # hr, moderate delay
    'chv': 3600.0,    # 1 m/s channel velocity
    'rv': 1800.0,     # 0.5 m/s overland velocity
    'srmax': 0.05,    # 50mm root zone
    'Q0': 0.00005,    # ~170 m³/s for Bengbu area
    'sr0': 0.002,     # small initial deficit
    'infex': 0,       # no infiltration excess
    'xk0': 1.0,       # surface Ksat
    'hf': 0.02,       # wetting front suction
    'dth': 0.1,       # moisture change
}
```
