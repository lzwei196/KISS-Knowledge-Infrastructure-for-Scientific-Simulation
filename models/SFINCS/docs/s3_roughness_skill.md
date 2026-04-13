# S3: Roughness — Skill Document

## Purpose

Generate spatially varying Manning's n roughness coefficient from land use/land cover data. Manning's n controls flow velocity and is the primary calibration parameter for SFINCS.

## Prerequisites

- grid_info.json from s1_domain
- AVHRR 1km land cover data (same as VIC vegetation, at `data/forcing/AVHRR/`)

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| grid_info.json | JSON | s1_domain | Yes |
| LULC raster | GeoTIFF | AVHRR or user-provided | Optional |
| Uniform n | number | User choice | Optional |

## Procedure

1. **Choose approach**:
   - LULC-based (recommended for heterogeneous domains): uses AVHRR land cover classification
   - Uniform (for quick tests): `--uniform_n 0.04` (typical floodplain)

2. **Run tool**: `build_sfincs_roughness.py --grid_info <json> --output_dir <dir>`

3. **Manning's n lookup table** (from Chow 1959, SFINCS documentation):

| Surface | Manning's n |
|---------|------------|
| Smooth water body | 0.020-0.025 |
| Concrete/pavement | 0.012-0.020 |
| Bare soil/gravel | 0.025-0.035 |
| Short grass/cropland | 0.030-0.045 |
| Tall grass/savanna | 0.035-0.045 |
| Shrubland | 0.035-0.050 |
| Urban residential | 0.060-0.100 |
| Dense urban | 0.080-0.120 |
| Forest | 0.100-0.160 |
| Snow/ice | 0.010-0.020 |

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| sfincs.man | `{output_dir}/sfincs.man` | nmax * mmax * 4 bytes |
| roughness_summary.json | `{output_dir}/roughness_summary.json` | mean n in 0.02-0.15 range |

## Validation Checks

1. Manning's n range: 0.015 to 0.20 (values outside this are suspect)
2. No cells with n < 0.01 (causes CFL instability, dt_020)
3. Mean n should match dominant land cover (e.g., 0.03-0.05 for agricultural floodplain)

## Common Pitfalls

- **dt_020**: Manning's n < 0.01 causes water to flow unrealistically fast, violating CFL.
- Using forest n=0.15 everywhere overestimates friction and underestimates flood extent.
- For urban areas, consider using elevated topography (buildings as barriers) instead of high n.
