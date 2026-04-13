# Stage 3: Muskingum Parameter Generation

## Purpose

Generate the two Muskingum routing parameters for each river reach:

- **k**: Wave travel time through the reach (SECONDS)
- **x**: Attenuation weighting factor (DIMENSIONLESS, range 0–0.5)

These control how flow is routed through the network. The Muskingum equation:

```
Q_out(t) = C1 × Q_in(t) + C2 × Q_in(t-1) + C3 × Q_out(t-1)

where:
  C1 = (-k×x + dt/2) / (k×(1-x) + dt/2)
  C2 = (k×x + dt/2)  / (k×(1-x) + dt/2)
  C3 = (k×(1-x) - dt/2) / (k×(1-x) + dt/2)
```

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Reach length | CSV/SHP attribute | meters | NHDPlus LENGTHKM × 1000, MERIT-Hydro |
| Channel slope | CSV/SHP attribute | m/m | NHDPlus SLOPE, MERIT-Hydro |
| Wave celerity | Estimated | m/s | Manning equation or empirical |
| riv_bas_id.csv | CSV | — | Stage 1 output |
| ZS_dtR | Scalar | seconds | Namelist routing sub-step |

## Outputs

| Output | Format | Units | Description |
|--------|--------|-------|-------------|
| k.csv | One value per line | seconds | Travel time per reach |
| x.csv | One value per line | dimensionless | Weighting factor per reach |
| kfac.csv (optional) | One value per line | dimensionless | k multiplier for calibration |
| xfac.csv (optional) | One value per line | dimensionless | x multiplier for calibration |

## Procedure

1. **Estimate wave celerity** for each reach:

   - **From Manning's equation** (preferred):
     ```
     c = (5/3) × (1/n) × R^(2/3) × S^(1/2)
     ```
     Simplified for typical rivers: `c ≈ 1.0 × S^0.3` m/s

   - **From published values**: 0.5–3.0 m/s for most rivers

   - **From NHDPlus velocity**: If available, use directly

2. **Compute k** for each reach:
   ```
   k = length_m / celerity_m_s   (result in seconds)
   ```

   Example: 10 km reach, c = 1.0 m/s → k = 10000 s ≈ 2.78 hours

3. **Set x** for each reach:
   - x = 0.0: Pure reservoir (maximum attenuation)
   - x = 0.1–0.3: Typical rivers (recommended default: 0.1)
   - x = 0.5: Pure translation (no attenuation) — rarely used

4. **Check Muskingum stability**:
   ```
   k × x ≤ dt/2 ≤ k × (1-x)
   ```
   If violated, either adjust k or reduce ZS_dtR.

5. **Write CSV files** with one value per line, ordered to match riv_bas_id.

## Verification

```bash
# Check file line counts match
wc -l k.csv x.csv riv_bas_id.csv

# Check k range (should be hundreds to tens of thousands of seconds)
python3 -c "
k = [float(l) for l in open('k.csv') if l.strip()]
print(f'k: min={min(k):.0f}s ({min(k)/3600:.2f}h), max={max(k):.0f}s ({max(k)/3600:.1f}h)')
"

# Check x range (should be 0.0–0.5)
python3 -c "
x = [float(l) for l in open('x.csv') if l.strip()]
print(f'x: min={min(x):.3f}, max={max(x):.3f}')
"

# Stability check
python3 -c "
import numpy as np
k = np.array([float(l) for l in open('k.csv') if l.strip()])
x = np.array([float(l) for l in open('x.csv') if l.strip()])
dt = 900  # ZS_dtR
lower = k * x
upper = k * (1 - x)
bad = np.sum((lower > dt/2) | (upper < dt/2))
print(f'Unstable reaches: {bad}/{len(k)}')
"
```

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| k in hours not seconds (dt_002) | FATAL | k too small → C1 or C3 < 0 → NaN in discharge |
| x > 0.5 (dt_003) | DEGRADED | Causes negative C3 → negative discharge oscillations |
| x = 0 everywhere (dt_010) | SILENT | Maximum damping → overly smooth hydrograph, no peaks |
| k too small for dtR (dt_008) | FATAL | Violates Courant condition → KSP solver diverges |
| Line count mismatch | FATAL | k.csv and x.csv must have same line count as riv_bas_id.csv |

## Example

For a basin with reaches of 5–50 km length and default celerity 1.0 m/s:

```
# k.csv (in seconds)
5000.0
10000.0
25000.0
50000.0
7500.0

# x.csv (dimensionless)
0.1
0.1
0.1
0.1
0.1
```

With ZS_dtR = 900s: stability bounds for k=5000, x=0.1 are
`500 ≤ 450 ≤ 4500` → lower bound violated! Need k ≥ 500/0.1 = 5000s at minimum.
