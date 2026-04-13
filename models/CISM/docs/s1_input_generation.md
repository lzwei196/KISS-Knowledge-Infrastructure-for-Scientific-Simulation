# Stage 1: Input Generation

## Purpose

Create the NetCDF input file containing initial conditions and boundary
conditions for CISM: bed topography (topg), ice thickness (thk), surface
air temperature (artm), surface mass balance (acab), and optionally basal
traction (beta).

## Inputs

| Input | Source | Required |
|-------|--------|----------|
| Grid dimensions | s0 (ewn, nsn, upn, dew, dns) | Yes |
| Topography data | DEM, BedMachine, or synthetic | Yes |
| Ice thickness | Observation or synthetic | Yes |
| Surface temperature | Climate data or synthetic | Yes |
| Surface mass balance | SMB model or synthetic | Yes |
| Basal traction | Inversion or synthetic | No |

## Outputs

| Output | Format | Used by |
|--------|--------|---------|
| input.nc | NetCDF (CISM format) | s3 ([CF input]), s4 (cism_driver) |

## Procedure

1. **Prepare coordinate arrays**:
   ```python
   x1 = np.arange(ewn) * dew    # scalar grid (m)
   y1 = np.arange(nsn) * dns
   x0 = (np.arange(ewn-1) + 0.5) * dew  # staggered grid
   y0 = (np.arange(nsn-1) + 0.5) * dns
   level = np.linspace(0, 1, upn)  # sigma: 0=surface, 1=base
   ```

2. **Create fields on scalar grid (y1, x1)**:
   - `topg[nsn, ewn]`: Bed topography in meters. Negative = below sea level.
   - `thk[nsn, ewn]`: Ice thickness in meters. Must be >= 0.
   - `artm[nsn, ewn]`: Surface air temperature in degrees Celsius.
   - `acab[nsn, ewn]`: Surface mass balance in **m/yr** (NOT mm/yr).

3. **Create fields on staggered grid (y0, x0)** (optional):
   - `beta[nsn-1, ewn-1]`: Basal traction coefficient in Pa yr/m.
   - `kinbcmask[nsn-1, ewn-1]`: Velocity boundary condition mask (0/1).

4. **Write NetCDF** with dimensions time, x1, y1, x0, y0, level.

5. **Validate output**: Check dimensions match config, no NaN values,
   thk >= 0, acab in reasonable range.

## Verification

- [ ] topg, thk, artm, acab all present in output NetCDF
- [ ] Dimensions: x1=ewn, y1=nsn, x0=ewn-1, y0=nsn-1
- [ ] acab is in m/yr (typical range: -10 to +5 for real ice sheets)
- [ ] thk has no negative values
- [ ] artm is in degrees Celsius (not Kelvin -- check max < 50)
- [ ] File can be read by `ncdump -h input.nc`

## Traps

| ID | Trap | Prevention |
|----|------|-----------|
| dt_001 | acab in mm/yr instead of m/yr | Check max(abs(acab)) < 50 |
| dt_006 | Grid coordinates in km not m | Verify x1 spacing matches dew |
| dt_012 | topg sign error (positive below SL) | topg < 0 means below sea level |
| dt_020 | NetCDF dimension mismatch | Verify dims match [grid] section |

## Example

```bash
# Generate dome test input
python tools/generate_input_nc.py --mode dome --ewn 31 --nsn 31 \
    --dew 2000 --upn 11 --output dome.nc

# Generate from real topography
python tools/generate_input_nc.py --mode custom \
    --topg bedmachine_topg.csv --thk bedmachine_thk.csv \
    --artm racmo_artm.csv --acab racmo_smb.csv \
    --ewn 301 --nsn 561 --dew 5000 --output greenland.nc
```
