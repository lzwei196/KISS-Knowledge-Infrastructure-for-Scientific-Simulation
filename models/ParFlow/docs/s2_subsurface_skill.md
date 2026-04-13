# S2: Subsurface Properties — Skill Document

## Purpose

Assign spatially distributed hydraulic properties (permeability, porosity, van Genuchten parameters, Manning's n) to every grid cell. These control how water moves through the subsurface and over the surface.

**If skipped**: ParFlow uses default uniform properties, which are unrealistic for heterogeneous basins.

## Prerequisites

- Domain definition (s1 complete)
- Domain mask (s1 complete)
- HWSD global raster (`data/soil/HWSD_RASTER/hwsd.bil`)

## CRITICAL UNIT TABLE

| Property | ParFlow Unit | MODFLOW Unit | SI Unit | Conversion Factor |
|----------|-------------|-------------|---------|-------------------|
| Permeability K | **m/hr** | m/day | m/s | K_m_hr = K_m_day / 24 = K_m_s * 3600 |
| van Genuchten alpha | **1/m** | n/a | 1/cm | alpha_1m = alpha_1cm * 100 |
| Pressure head | **m water** | m water | Pa | h_m = P_Pa / 9810 |
| Specific storage | **1/m** | 1/m | 1/m | Same |
| Porosity | dimensionless | dimensionless | dimensionless | Same |
| Manning's n | s/m^(1/3) | n/a | s/m^(1/3) | Same |

**THE #1 SILENT ERROR in ParFlow is wrong K units (dt_pf_001).** Always verify.

## Procedure

1. **Run** `build_subsurface_properties.py` with domain_json and mask_npy.
   - The tool reads HWSD raster, classifies soil texture, applies Rosetta pedotransfer.
   - Output: permeability_x/y/z.npy, porosity.npy, vangenuchten_alpha/n.npy, etc.
   - **Verify K range**: Typical 1e-6 (clay) to 0.03 (sand) m/hr.
   - **Verify alpha range**: Typical 0.5 (clay) to 15 (sand) 1/m.

2. **Set K anisotropy** (Kz/Kx ratio):
   - Default 0.1 (layered sediments: vertical flow 10x slower than horizontal).
   - Isotropic: 1.0 (fractured rock, uniform sand).
   - Very low: 0.01 (strongly layered clays).

3. **Run** `build_mannings.py` for overland flow roughness.
   - Output: mannings_n.npy.
   - **Verify range**: 0.01 (urban) to 0.4 (dense forest).
   - **CRITICAL**: Manning's n < 0.01 causes CFL instability. Tool enforces minimum.

## Expected Outputs

| Output | Verification |
|--------|--------------|
| permeability_x/y/z.npy | Values 1e-6 to 0.1 m/hr |
| porosity.npy | Values 0.2 to 0.6 |
| vangenuchten_alpha.npy | Values 0.5 to 15 (1/m, NOT 1/cm) |
| vangenuchten_n.npy | Values 1.05 to 4.0 |
| mannings_n.npy | Values 0.01 to 0.4 |

## Common Pitfalls

- **K units** (dt_pf_001): m/day from MODFLOW literature gives 24x too much flow
- **Alpha units** (dt_pf_005): 1/cm from Rosetta raw output gives 100x more retentive soil
- **PFMG failure** (dt_pf_022): K contrast > 6 orders of magnitude causes solver crash
- **Zero Manning's n**: Causes division by zero in overland flow equation
