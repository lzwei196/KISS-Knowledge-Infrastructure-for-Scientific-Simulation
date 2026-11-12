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
| 7 | Q0 | m/step (m/day on the daily route) | 1e-6–1e-3 | Initial subsurface flow, same unit as Q |
| 8 | sr0 | m | 0–srmax | Initial root zone deficit |
| 9 | infex | 0/1 | — | Infiltration excess flag (usually 0) |
| 10 | xk0 | m/hr | 0.01–10 | Surface hydraulic conductivity |
| 11 | hf | m | 0.01–0.5 | Wetting front suction (Green-Ampt) |
| 12 | dth | — | 0–1 | Water content change at wetting front |

Units above are the upstream hourly labels. The rate parameters (t0, td, chv, rv, xk0) are per model step: on the daily route (`--dt-hours 24`) read "hr" as "day" (chv and rv in m/hr × 24, td in hr ÷ 24, ln(T0) + ln 24).

## Procedure

1. **Estimate szm from soil data**:
   - Related to soil depth and transmissivity profile
   - Sandy soils: szm ~ 0.01–0.03
   - Clay soils: szm ~ 0.03–0.08
   - Use HWSD soil texture class as guide

2. **Estimate t0 from hydraulic conductivity**:
   - T0 = Ksat × soil_depth (approximate), then set t0 = ln(T0)  # binary exponentiates t0
   - Ksat from HWSD or SoilGrids
   - Convert Ksat given in cm/day: ÷ 100 gives m/day (the daily route); ÷ 2400 gives m/hr (hourly steps only)

3. **Estimate srmax from land cover**:
   - Forest: srmax ~ 0.05–0.15 m
   - Cropland: srmax ~ 0.02–0.08 m
   - Grassland: srmax ~ 0.01–0.05 m

4. **Set channel/routing velocities**:
   - chv and rv are metres per model step (m/s × physical_seconds_per_step)
   - On the daily route (`--dt-hours 24`): chv typically 24,000–120,000 m/day (0.3–1.4 m/s), rv 12,000–86,400 m/day (0.15–1.0 m/s)
   - `calibrate_topmodel.py` samples both as 10^4.7–10^5.8 m/day (about 50,000–630,000 m/day, 0.6–7.3 m/s)
   - Only at `--dt-hours 1` are the same speeds chv 1000–5000 m/hr and rv 500–3600 m/hr

5. **Set initial conditions**:
   - Q0: estimate from observed low flow, in the same unit as Q: Q0 = Q_m3s × physical_seconds_per_step / area_m2 (86400 on the daily route)
   - sr0: start at 0 (near field capacity) or small value
   - sr0 must be ≤ srmax

6. **Write params.dat**:
   ```
   Basin Name
   {szm}  {t0}  {td}  {chv}  {rv}  {srmax}  {Q0}  {sr0}  {infex}  {xk0}  {hf}  {dth}
   ```

## Verification

- [ ] All parameters are in correct units (metres and the model step: per day on the daily route)
- [ ] sr0 ≤ srmax
- [ ] Q0 > 0 (non-zero initial flow)
- [ ] infex = 0 unless infiltration excess is expected
- [ ] Parameter values are within physically reasonable ranges
- [ ] szm > 0 (zero causes division by zero)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Ksat in cm/day, used as m/hr | T0 off by 2400× (t0 = ln T0 off by ln 2400 ≈ 7.8) | Convert: m/hr = cm/day / 2400; on the daily route m/day = cm/day / 100 |
| srmax = 0 | Division by zero in ET calc | Set srmax > 0.001 |
| sr0 > srmax | Invalid initial state | Ensure sr0 ≤ srmax |
| chv or rv in m/s, not m per model step | Routing far too slow (86400× on the daily route, 3600× at `--dt-hours 1`) | chv_step = chv_ms × physical_seconds_per_step (86400 on the daily route; 3600 only at `--dt-hours 1`); the same for rv |
| Q0 in m³/s, or converted with 3600 on a daily run | Wrong initial flow (24× too low with 3600 on the daily route) | Q0 = Q0_m3s × physical_seconds_per_step / area_m2 (86400 on the daily route) |

## Example

```python
# Bengbu basin - reasonable starting parameters for the daily route (--dt-hours 24; one model step = one day)
params = {
    'szm': 0.04,      # moderate for mixed soils
    't0': 8.18,       # ln(T0), T0 per day: ln(148 x 24) = 5 + ln 24 (148 m/hr); use 5.0 only at --dt-hours 1
    'td': 1.25,       # model steps = days on the daily route (30 hr / 24); use 30 only at --dt-hours 1
    'chv': 86400.0,   # m/day = 1 m/s channel velocity; use 3600 only at --dt-hours 1
    'rv': 43200.0,    # m/day = 0.5 m/s overland velocity; use 1800 only at --dt-hours 1
    'srmax': 0.05,    # 50mm root zone
    'Q0': 0.00005,    # m per step, same unit as Q (m/day on the daily route)
    'sr0': 0.002,     # small initial deficit
    'infex': 0,       # no infiltration excess
    'xk0': 1.0,       # surface Ksat
    'hf': 0.02,       # wetting front suction
    'dth': 0.1,       # moisture change
}
```
