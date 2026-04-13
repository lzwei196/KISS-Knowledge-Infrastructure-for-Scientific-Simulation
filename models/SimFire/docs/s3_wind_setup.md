# S3: Wind Setup — Configuring Wind Fields for SimFire

## Purpose

Configure the wind speed and direction fields that drive fire spread in the Rothermel
equation. Wind is the dominant factor in fire spread rate — incorrect wind setup is
the most common cause of unrealistic fire behavior.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Wind speed | Measurement/model | scalar or 2D array | **ft/min** (internally) |
| Wind direction | Measurement/model | scalar or 2D array | degrees (0=N, CW) |
| Wind mode | Config | string | "simple", "perlin", "cfd" |

## Outputs

| Output | Format | Units | Shape |
|--------|--------|-------|-------|
| Wind speed array | numpy float | ft/min | (H, W) |
| Wind direction array | numpy float | degrees [0, 360) | (H, W) |

## Procedure

### Option A: Simple (Constant) Wind

Uniform speed and direction across entire domain. Good for testing.

```yaml
wind:
  function: simple
  simple:
    speed: 1760       # ft/min (= 20 mph × 88)
    direction: 90.0   # degrees (0=N, 90=E wind blows FROM east)
```

**CRITICAL CONVERSION**: The `speed` value must be in **ft/min**.
| Common Source | Conversion | Example |
|---------------|------------|---------|
| 10 mph | × 88 = 880 ft/min | Light breeze |
| 20 mph | × 88 = 1760 ft/min | Moderate wind |
| 5 m/s | × 196.85 = 984 ft/min | Moderate breeze |
| 30 km/h | × 54.68 = 1640 ft/min | Fresh breeze |

### Option B: Perlin Noise Wind

Spatially varying wind using Simplex noise. Produces naturalistic variation.

```yaml
wind:
  function: perlin
  perlin:
    speed:
      seed: 2345
      scale: 400          # noise spatial frequency
      octaves: 3          # detail passes
      persistence: 0.7    # amplitude decay per octave
      lacunarity: 2.0     # frequency increase per octave
      range_min: 7        # minimum speed (ft/min)
      range_max: 47       # maximum speed (ft/min)
    direction:
      seed: 650
      scale: 1500
      octaves: 2
      persistence: 0.9
      lacunarity: 1.0
      range_min: 0.0      # degrees
      range_max: 360.0    # degrees
```

**Note**: `range_min` and `range_max` for speed are in **ft/min**.
A range of 7–47 ft/min = 0.08–0.53 mph. This is very slow wind.
For realistic conditions, use e.g., `range_min: 440, range_max: 2640` (5–30 mph).

### Option C: CFD Wind

Computational Fluid Dynamics wind using Navier-Stokes solver. Accounts for terrain
effects on wind flow.

```yaml
wind:
  function: cfd
  cfd:
    time_to_train: 1000    # CFD solver iterations (convergence)
    result_accuracy: 1
    iterations: 1
    scale: 1
    timestep_dt: 1.0
    diffusion: 0.0
    viscosity: 0.0000001
    speed: 19.0             # boundary condition speed (ft/min)
    direction: north        # boundary condition direction (compass name)
```

### Converting External Wind Data

Use `convert_wind_to_simfire.py` for external sources:

```bash
# From weather station data in mph
python ki/tools/convert_wind_to_simfire.py \
    --speed 20 --speed-unit mph \
    --direction 270 \
    --grid-shape 225 450 \
    --output-dir ./wind_data/

# From ERA5/MERRA2 in m/s
python ki/tools/convert_wind_to_simfire.py \
    --csv era5_wind.csv \
    --speed-col u10 --dir-col wind_dir \
    --speed-unit ms \
    --grid-shape 225 450 \
    --output-dir ./wind_data/
```

## Wind Direction Convention

SimFire uses **meteorological convention**: direction the wind blows FROM.

| Direction | Degrees | Fire spreads toward |
|-----------|---------|---------------------|
| North | 0° | South |
| East | 90° | West |
| South | 180° | North |
| West | 270° | East |

The Rothermel model extracts the wind component along the direction from the
current pixel to each neighbor. Only the positive (pushing) component is used;
negative (opposing) wind is clamped to zero.

## Verification

1. Check wind speed is in ft/min (not mph):
   ```python
   # If max speed < 100 ft/min, likely in mph (forgot ×88)
   # 100 ft/min = 1.14 mph — almost no wind
   assert wind_speed.max() > 100, "Wind likely in mph, not ft/min"
   ```

2. Check direction range:
   ```python
   assert 0 <= wind_dir.min() and wind_dir.max() < 360
   ```

3. Visual sanity: fire should elongate downwind
   ```python
   # East wind (90°) → fire should spread westward
   # Fire elongation axis should align with wind direction
   ```

## Traps

| Trap | Symptom | Severity | Fix |
|------|---------|----------|-----|
| Speed in mph instead of ft/min | Fire barely moves | **Silent** | Multiply by 88 |
| Speed in m/s instead of ft/min | Fire barely moves | **Silent** | Multiply by 196.85 |
| Perlin range_min/max in mph | Very slow wind field | **Silent** | Use ft/min values |
| Direction in radians | Erratic fire direction | **Silent** | Convert to degrees |
| CFD too few training iterations | Wind field not converged | **Silent** | Increase `time_to_train` |
| Math convention (0=E, CCW) | Fire spreads wrong direction | **Silent** | Convert to met convention |

## Example

For a 20 mph east wind (common Santa Ana condition):
```yaml
wind:
  function: simple
  simple:
    speed: 1760    # 20 mph × 88 = 1760 ft/min
    direction: 90  # from east
```
