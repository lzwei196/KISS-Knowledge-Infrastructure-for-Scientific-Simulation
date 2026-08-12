# S3: Wind Setup — Configuring Wind Fields for SimFire

## Purpose

Configure the wind speed and direction fields that drive fire spread in the
Rothermel equation. Wind is the dominant factor in fire spread rate —
incorrect wind setup is the most common cause of unrealistic fire behavior.

## ⚠️ Two unit/convention bugs to avoid (re-verified 2026-04-29)

These contradict what some older project docs said; the source is authoritative:

1. **YAML `wind.simple.speed` is in MPH, not ft/min.**
   `simfire/utils/config.py:860` does:
   ```python
   speed = mph_to_ftpm(self.yaml_data["wind"]["simple"]["speed"])
   ```
   So if you write `speed: 1760` (intending "20 mph × 88 ft/min"),
   SimFire reads it as 1760 mph → 154,880 ft/min — fire fills the grid in
   minutes. Just write `speed: 20`.
   Same conversion applies to `wind.perlin.speed.range_min/max`
   (`config.py:897-901`).

2. **YAML `wind.simple.direction` is "TO direction", not meteorological "from".**
   `simfire/world/rothermel.py:104` computes
   `wind_angle_radians = np.radians(90 − U_dir)` and then projects the wind
   vector onto the spread direction; max RoS occurs when
   `angle_of_travel == U_dir`. So:
   - `direction = 90` → wind blows **toward East** (fire spreads East)
   - `direction = 225` → wind blows **toward Southwest** (fire spreads SW)
   - For a Diablo NE wind that blows TO SW, write `direction: 225`,
     NOT `direction: 45`.

## Inputs

| Input | Source | Format | YAML unit | Internal unit |
|-------|--------|--------|-----------|---------------|
| Wind speed | weather obs / model | scalar | **mph** | ft/min |
| Wind direction | weather obs / model | scalar | degrees, "TO direction" | same |
| Wind mode | config | string | `simple` / `perlin` / `cfd` | — |

## Procedure

### Option A: Simple (constant) wind — recommended for case studies

Uniform speed and direction across the entire domain.

```yaml
wind:
  function: simple
  simple:
    speed: 20            # mph (NOT ft/min). config.py:860 applies mph_to_ftpm
    direction: 90.0      # degrees, "TO" convention. 90 = wind blows TOWARD East.
```

| You want… | direction |
|---|---|
| Wind FROM N (blowing TO S) | 180 |
| Wind FROM E (blowing TO W) | 270 |
| Wind FROM S (blowing TO N) | 0 |
| Wind FROM W (blowing TO E) | 90 |
| Wind FROM NE (blowing TO SW; Diablo) | 225 |
| Wind FROM SW (blowing TO NE) | 45 |

### Option B: Perlin noise wind

Spatially varying wind using Simplex noise.

```yaml
wind:
  function: perlin
  perlin:
    speed:
      seed: 2345
      scale: 400
      octaves: 3
      persistence: 0.7
      lacunarity: 2.0
      range_min: 5         # mph (NOT ft/min)
      range_max: 30         # mph
    direction:
      seed: 650
      scale: 1500
      octaves: 2
      persistence: 0.9
      lacunarity: 1.0
      range_min: 0.0        # degrees, "TO direction"
      range_max: 360.0
```

### Option C: CFD wind

Computational Fluid Dynamics wind using a Navier-Stokes solver. The
`speed` here is a boundary-condition magnitude in **m/s**; the resulting
spatial array is converted via `scale_ms_to_ftpm` (`config.py:891`).

```yaml
wind:
  function: cfd
  cfd:
    time_to_train: 1000     # CFD solver iterations
    speed: 8.9              # m/s boundary condition (~20 mph)
    direction: north        # boundary direction (compass name)
    # ... + diffusion / viscosity / scale / timestep_dt etc.
```

### Converting external wind data

`tools/convert_wind_to_simfire.py` exists for advanced workflows that need
to **inject pre-computed wind arrays** (e.g. into a CFD or custom layer
pipeline). It produces `.npy` arrays in **ft/min** because that's what
the Rothermel internals expect.

For the standard `simple` and `perlin` paths, **do not** use the
ft/min outputs of this tool as YAML scalars — those YAML scalars are
already mph. Just write the mph value directly.

## Verification

1. **Sanity-check sim wind against intent.** After loading the config,
   confirm internal units:
   ```python
   from simfire.utils.units import mph_to_ftpm
   intended_mph = 20
   internal_ftmin = mph_to_ftpm(intended_mph)   # 1760 ft/min
   ```
   If your sim is spreading 88× faster than expected, you almost certainly
   double-converted (wrote ft/min in the YAML).

2. **Check direction alignment.** Run a short sim with wind blowing toward
   East (`direction: 90`) on a square grid; fire should elongate **eastward**
   from the ignition point. If it elongates west, you've used the
   meteorological "from" convention.

3. Direction range:
   ```python
   assert 0 <= wind_dir < 360
   ```

## Traps

| Trap | Symptom | Severity | Fix |
|------|---------|----------|-----|
| YAML `simple.speed` written as ft/min (e.g. 1760) | Fire fills grid in minutes; sim/expected RoS ratio ≈ 88× | **Silent** | Write the mph value (20), not 1760 |
| YAML `simple.direction` set per meteorological "from" convention | Fire spreads OPPOSITE the intended downwind direction | **Silent** | Use "TO direction": for "wind from NE", write 225 not 45 |
| Perlin `range_min/max` written as ft/min | Wind field 88× too strong | **Silent** | Use mph values |
| `convert_wind_to_simfire.py` ft/min outputs pasted into YAML | Wind 88× too strong | **Silent** | Use that tool only for spatial wind ARRAYS in CFD/custom layers; the simple/perlin YAML scalars are mph |
| Direction in radians | Erratic fire direction | **Silent** | Convert to degrees |
| CFD too few training iterations | Wind field not converged | **Silent** | Increase `time_to_train` |

## Example

For a 20 mph Diablo wind (NE → SW):
```yaml
wind:
  function: simple
  simple:
    speed: 20         # mph
    direction: 225    # blows TO SW
```
