# S4: Forcing & Boundary Conditions — Skill Document

## Purpose

Prepare all forcing inputs for SFINCS: precipitation (rainfall), river discharge boundaries (from CaMa-Flood), and optionally tidal/surge boundaries for coastal domains. This is the most error-prone stage due to **unit conversions**.

## Prerequisites

- grid_info.json from s1_domain
- For rainfall: CMFD/MSWX forcing data or VIC forcing ASCII files
- For river BC: CaMa-Flood output (outflw.nc and/or sfcelv.nc)
- For tidal BC: FES2014 tidal model (not yet integrated — future)

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| grid_info.json | JSON | s1_domain | Yes |
| Forcing directory | directory | VIC forcing or CMFD/MSWX | For rainfall |
| CaMa-Flood output dir | directory | CaMa-Flood run | For river BC |
| Start/end dates | string | User | Yes |

## Procedure

### A. Precipitation Forcing

1. **Run tool**: `prepare_sfincs_rainfall.py --forcing_dir <dir> --grid_info <json> --start_date <date> --end_date <date> --source <cmfd|mswx|vic_ascii> --output_dir <dir>`

2. **CRITICAL UNIT CONVERSION**:

| Source | Native Unit | SFINCS Unit | Conversion |
|--------|-----------|-------------|------------|
| CMFD | mm/3hr | mm/hr | **divide by 3** |
| MSWX | mm/3hr | mm/hr | **divide by 3** |
| VIC ASCII (precip column) | mm/3hr | mm/hr | **divide by 3** |
| Climate models (kg/m2/s) | m/s | mm/hr | **multiply by 3,600,000** |
| mm/day | mm/day | mm/hr | **divide by 24** |

   The tool handles this automatically, but VERIFY: check `rainfall_summary.json`:
   - `precip_max_mmhr` should be < 100 mm/hr (< 200 for extreme events)
   - If > 200: units are probably wrong (dt_001)
   - If < 0.01 during a known storm: units are probably wrong (dt_002)

3. **Spatial approach**: Current tool creates spatially uniform precipitation from the forcing data average. For heterogeneous rainfall over large domains (>50km), spatially varying NetCDF is needed — use HydroMT-SFINCS for more sophisticated spatial interpolation.

### B. CaMa-Flood River Boundary Conditions

1. **Choose BC type**:
   - **Discharge** (sfincs.src + sfincs.dis): For upstream river entry points. CaMa outflw is in m3/s.
   - **Water level** (sfincs.bnd + sfincs.bzs): For downstream/coastal boundaries. CaMa sfcelv is in m.

2. **Run tool**: `cama_to_sfincs_boundary.py --cama_out_dir <dir> --grid_info <json> --bc_type discharge --auto --start_date <date> --end_date <date> --output_dir <dir>`

3. **Verify boundary_summary.json**:
   - Discharge values > 0 for inflow (dt_015)
   - Values are in correct range for the river (10-10,000 m3/s typical)

### C. Avoiding Double-Counting (dt_014)

**CRITICAL**: Choose ONE of these approaches:
- **(a) Recommended**: SFINCS with its own rainfall + CaMa river discharge BC only. The SFINCS domain handles local rainfall-runoff; CaMa provides upstream river flow.
- **(b) Alternative**: SFINCS without rainfall, only CaMa-Flood runoff as source. Misses local pluvial flooding.
- **NEVER**: Apply both VIC surface runoff AND precipitation in SFINCS. This doubles the water volume.

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| sfincs.precip | `{output_dir}/sfincs.precip` | NetCDF with units=mm/hr |
| sfincs.src | `{output_dir}/sfincs.src` | Source point coordinates |
| sfincs.dis | `{output_dir}/sfincs.dis` | Discharge time series (m3/s) |
| sfincs.bnd | `{output_dir}/sfincs.bnd` | Water level boundary locations |
| sfincs.bzs | `{output_dir}/sfincs.bzs` | Water level time series (m) |

## Validation Checks

1. Precipitation max < 200 mm/hr (if higher, check units — dt_001)
2. Precipitation not all zero during known storm period (dt_002)
3. Discharge values positive for inflow points (dt_015)
4. Boundary points fall on active mask cells (dt_012)
5. No double-counting (dt_014)

## Common Pitfalls

- **dt_001**: The #1 silent error. mm/3hr passed as mm/hr = 3x too much rain.
- **dt_002**: m/s passed as mm/hr = effectively zero rain.
- **dt_003**: VIC mm/day passed as CaMa m3/s = 86,400x too small.
- **dt_012**: BC point on inactive cell — silently ignored.
- **dt_014**: Both rainfall and VIC runoff in SFINCS = double water.
- **dt_016**: Daily CaMa output for sub-hourly SFINCS = artificial 24hr ramps.
