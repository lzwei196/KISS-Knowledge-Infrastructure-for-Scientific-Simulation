# Stage 3: Parameter Configuration

## Purpose

Configure the physical parameterizations, initial conditions, and numerical parameters in `constants.toml` to match the glacier site characteristics and desired simulation setup.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Glacier characteristics | Literature / field data | Physical parameters |
| Calibration data | Stake measurements / remote sensing | Observed MB |
| Previous runs | Sensitivity analysis | Parameter ranges |

## Outputs

| Output | Path | Format |
|--------|------|--------|
| `constants.toml` | Working directory | TOML |

## Procedure

### 1. General settings

```toml
[GENERAL]
dt = 3600           # Must match input data time step [s]
max_layers = 200    # Increase if "Maximum number of layers" error occurs
z = 2.0             # Measurement height [m] — match to forcing data height
```

### 2. Parameterization choices

| Parameter | Options | Recommendation |
|-----------|---------|----------------|
| `stability_correction` | `Ri`, `MO` | `Ri` (Richardson number — simpler, robust) |
| `albedo_method` | `Oerlemans98`, `Bougamont05` | `Oerlemans98` (standard, well-tested) |
| `densification_method` | `Boone`, `empirical`, `constant` | `Boone` (physically-based) |
| `penetrating_method` | `Bintanja95` | `Bintanja95` (only option) |
| `roughness_method` | `Moelg12` | `Moelg12` (only option) |
| `sfc_temperature_method` | `Secant`, `L-BFGS-B`, `SLSQP` | `Secant` (fastest, recommended) |

### 3. Initial conditions

| Parameter | Default | Description | Sensitivity |
|-----------|---------|-------------|-------------|
| `initial_snowheight_constant` | 0.2 m | Starting snow depth | HIGH — affects first months |
| `initial_glacier_height` | 40.0 m | Ice thickness | LOW — glacier won't melt through |
| `initial_glacier_layer_heights` | 0.5 m | Ice layer thickness | LOW |
| `initial_top_density_snowpack` | 300 kg/m3 | Surface snow density | MEDIUM |
| `initial_bottom_density_snowpack` | 600 kg/m3 | Base snow density | LOW |
| `temperature_bottom` | 270.16 K | Bottom temperature BC | MEDIUM |

### 4. Precipitation parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `center_snow_transfer_function` | 1.0 | Temperature offset for snow/rain partition (K above 0C) |
| `spread_snow_transfer_function` | 1 | Sharpness of partition (1 = gradual, higher = sharper) |
| `mult_factor_RRR` | 1.0 | Precipitation multiplication factor |
| `minimum_snowfall` | 0.001 m | Minimum snowfall to create new layer |

### 5. Albedo constants

| Parameter | Default | Units | Source |
|-----------|---------|-------|--------|
| `albedo_fresh_snow` | 0.85 | - | Moelg et al. 2012 |
| `albedo_firn` | 0.55 | - | Moelg et al. 2012 |
| `albedo_ice` | 0.3 | - | Moelg et al. 2012 |
| `albedo_mod_snow_aging` | 22 | days | Oerlemans & Knap 1998 |
| `albedo_mod_snow_depth` | 3 | cm | Oerlemans & Knap 1998 |

**For tropical/HMA glaciers**: Use `albedo_mod_snow_aging = 6` and `albedo_mod_snow_depth = 8` (Moelg et al. 2012).

### 6. Remeshing parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `remesh_method` | `log_profile` | Layer merging strategy |
| `first_layer_height` | 0.01 m | Top layer always this thick |
| `layer_stretching` | 1.20 | Each layer 20% thicker than previous |
| `merge_max` | 1 | Max merges per timestep |
| `density_threshold_merging` | 5 kg/m3 | Density difference for merge |
| `temperature_threshold_merging` | 0.01 K | Temperature difference for merge |

## Verification

```bash
python -c "
import tomllib
with open('constants.toml', 'rb') as f: cst = tomllib.load(f)
print('dt:', cst['GENERAL']['dt'], 's')
print('max_layers:', cst['GENERAL']['max_layers'])
print('albedo method:', cst['PARAMETERIZATIONS']['albedo_method'])
print('initial snow:', cst['INITIAL_CONDITIONS']['initial_snowheight_constant'], 'm')
print('glacier height:', cst['INITIAL_CONDITIONS']['initial_glacier_height'], 'm')
"
```

## Traps

1. **dt mismatch with input data**: The single most impactful parameter error. All mass balance terms scale linearly with dt. If dt=3600 but input is 3-hourly (10800s), melt is 3x too low.

2. **Initial snow height affects spinup**: Setting `initial_snowheight_constant = 0` when snow exists causes immediate bare-ice albedo (0.3), dramatically increasing melt. Use a spinup period of at least 1 year.

3. **L-BFGS-B and SLSQP produce different results since Feb 2024**: Due to a code update, these optimizers give different (potentially wrong) surface temperatures. Use `Secant` (recommended) or investigate before using others.

4. **max_layers too low**: If snowfall is heavy, the model can create hundreds of layers. The restart file allocates max_layers entries, so this also affects disk space.

5. **mult_factor_RRR silently scales all precipitation**: This factor multiplies both RRR and SNOWFALL. Setting it to 1.5 for undercatch correction affects the entire mass balance.

## Example

```toml
# constants.toml for High Mountain Asia glacier (summer accumulation type)
[GENERAL]
dt = 3600
max_layers = 200
z = 2.0

[PARAMETERIZATIONS]
stability_correction = 'Ri'
albedo_method = 'Oerlemans98'
densification_method = 'Boone'
sfc_temperature_method = 'Secant'

[INITIAL_CONDITIONS]
initial_snowheight_constant = 0.5    # 50cm starting snow
initial_glacier_height = 40.0
temperature_bottom = 271.16          # -2C at glacier base

[CONSTANTS]
albedo_mod_snow_aging = 6            # tropical/HMA setting
albedo_mod_snow_depth = 8            # tropical/HMA setting
```
