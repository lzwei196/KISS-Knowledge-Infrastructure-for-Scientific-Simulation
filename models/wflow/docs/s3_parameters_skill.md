# s3 — Parameter Configuration Skill Document

## Purpose

Generate the wflow TOML configuration file and optionally adjust parameters for calibration. The TOML file is wflow's primary configuration — it specifies model type, routing method, input/output paths, and parameter modifications (scale/offset). TOML format errors or version mismatches cause fatal failures (dt_w006, dt_w011, dt_w022).

## Prerequisites

- Stage s1 complete (staticmaps.nc exists)
- Stage s2 complete (forcing.nc exists)
- Knowledge of wflow TOML format version (v1.0+ vs pre-v1.0)

## Inputs

| Name | Type | Source | Description |
|------|------|--------|-------------|
| wflow_config.yaml | file | s0 | HydroCraft config |
| staticmaps.nc | file | s1 | Spatial parameters |
| forcing.nc | file | s2 | Meteorological forcing |

## Procedure

1. Run `generate_wflow_toml.py --config wflow_config.yaml --output wflow_sbm.toml`
2. Verify TOML is valid: `python -c "import tomllib; tomllib.load(open('wflow_sbm.toml','rb'))"`
3. Check that paths in TOML point to existing files (staticmaps.nc, forcing.nc)
4. For calibration, use `adjust_parameters.py` to modify scale/offset values

### Parameter Adjustment for Calibration

wflow applies: `actual_value = netcdf_value * scale + offset`

Key calibration parameters (priority order):

| Parameter | Unit | Range | Sensitivity | What it controls |
|-----------|------|-------|-------------|-----------------|
| KsatVer | mm/day | 10-10000 | HIGH | Infiltration rate |
| f | 1/mm | 0.0005-0.005 | HIGH | Baseflow vs quickflow partitioning |
| SoilThickness | mm | 500-5000 | HIGH | Total water storage |
| RootingDepth | mm | 100-2000 | MEDIUM | ET extraction depth |
| N_River | s/m^(1/3) | 0.02-0.1 | MEDIUM | Flow velocity / timing |
| PathFrac | - | 0-0.3 | MEDIUM | Direct runoff fraction |

### Cross-Model Parameter Transfer (DANGER — dt_w026)

| From Model | Ksat Unit | To wflow (mm/day) | Conversion |
|------------|-----------|-------------------|------------|
| VIC | mm/s | multiply by 86400 | |
| MODFLOW | m/day | multiply by 1000 | |
| ParFlow | m/hr | multiply by 24000 | |

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| wflow_sbm.toml | outputs/<run>/wflow_project/wflow_sbm.toml | Valid TOML, paths resolve |

## Validation Checks

1. TOML parses without error
2. All referenced file paths exist
3. starttime and endtime match simulation period
4. timestepsecs matches forcing temporal resolution
5. Parameter scale values are reasonable (not 0 unless intended — dt_w012)

## Common Pitfalls

- **dt_w006**: v1.0 TOML on pre-v1.0 Wflow (MethodError)
- **dt_w010**: Variable name in TOML not in staticmaps.nc (KeyError)
- **dt_w011**: Invalid TOML syntax (parse error)
- **dt_w012**: scale=0 makes parameter uniform zero
- **dt_w022**: Online examples use pre-v1.0 format — they won't work with v1.0+
- **dt_w026**: Cross-model Ksat unit mismatch (86400x error)
