# S1: Configuration — Creating SimFire YAML Config Files

## Purpose

Create a valid SimFire YAML configuration file that defines all simulation parameters:
area dimensions, display settings, terrain sources, wind fields, fire ignition, fuel moisture,
and output options. The config file is the single entry point for all SimFire runs.

## Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| Simulation requirements | User specification | — | Duration, area size, location |
| Terrain mode | User choice | string | "operational", "functional", or "historical" |
| Wind mode | User choice | string | "simple", "perlin", or "cfd" |
| Geographic bounds (operational) | Lat/lon coordinates | decimal degrees | Top-left corner |
| Fire ignition point | User choice | (row, col) pixels | Or "random" with seed |

## Outputs

| Output | Format | Location |
|--------|--------|----------|
| YAML config file | `.yml` | `configs/` directory |

## Procedure

### Step 1: Choose terrain mode

- **Operational** (real-world): Requires `latitude`, `longitude`, `height` (m), `width` (m), `resolution` (30m), `year` (2019/2020/2022). Downloads LandFire FBFM-13 fuel and elevation.
- **Functional** (procedural): No external data needed. Uses Perlin noise for topography and `chaparral` for uniform fuel.
- **Historical**: Requires BurnMD data. Replays actual fire events.

### Step 2: Configure area dimensions

```yaml
area:
  screen_size: [H, W]    # pixels — determines simulation grid size
  pixel_scale: 50         # feet per pixel (MUST be in feet, NOT meters)
```

The physical domain size is: `H × pixel_scale` ft tall, `W × pixel_scale` ft wide.

**Example**: `[225, 450]` at 50 ft/pixel = 11,250 ft × 22,500 ft ≈ 3.4 km × 6.9 km

### Step 3: Configure wind

```yaml
wind:
  function: simple        # simple | perlin | cfd
  simple:
    speed: 20             # **mph** (config.py:860 calls mph_to_ftpm)
    direction: 90.0       # degrees, "TO direction": 90 = wind blows TOWARD East
```

**CRITICAL** (verified against simfire 2.0.1 source + `docs/source/config.md`):
- `wind.simple.speed` is in **mph**. SimFire converts to ft/min internally
  (`config.py:860`). Writing the converted value directly results in
  88× too-strong wind.
- `wind.simple.direction` is "TO direction", NOT meteorological "from".
  `direction = 90` means wind blowing TOWARD East. For "wind from NE"
  (Diablo), use `direction: 225` (toward SW).
- Same units apply to `wind.perlin.speed.range_min/max` (mph).

### Step 4: Set environment

```yaml
environment:
  moisture: 0.03          # FRACTION (3%), not percentage
```

**CRITICAL**: Moisture is a fraction (0.0–1.0), NOT a percentage (0–100).
If `M_f >= M_x` (moisture of extinction for the fuel), fire will not spread.

### Step 5: Configure fire ignition

```yaml
fire:
  fire_initial_position:
    type: static           # or "random"
    static:
      position: (25, 25)   # (row, col) in PIXELS, not meters
  max_fire_duration: 5     # frames before sprite pruning
  diagonal_spread: true    # 8-directional if true, 4-directional if false
```

### Step 6: Set simulation parameters

```yaml
simulation:
  update_rate: 1           # minutes per step (1 step = 1 minute of simulated time)
  runtime: "6h"            # supports "Xd Xh Xm" format
  headless: true           # MUST be true for server/batch runs
  record: false            # save GIF (requires display memory)
  save_data: true          # save fire map arrays
  data_type: "npy"         # "npy" or "h5"
```

## Verification

1. Parse the YAML and check all required sections exist:
   ```bash
   python -c "import yaml; yaml.safe_load(open('config.yml'))"
   ```
2. Check wind speed (YAML mph) is reasonable: typical 0–60 mph for surface wind
3. Check moisture is a fraction: should be 0.001–0.40, never > 1.0
4. Check pixel_scale is in feet: typically 30–100 ft

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Wind written as ft/min in YAML simple.speed | Fire spreads 88× too fast / fills grid in minutes | Write the mph value directly (e.g. 20, not 1760) |
| Wind direction interpreted as meteorological "from" | Fire spreads OPPOSITE downwind | YAML direction is "TO": for "wind from NE", use 225 not 45 |
| Moisture as percentage | Fire never spreads | Divide by 100 |
| `headless: false` on server | PyGame crash | Set `headless: true` |
| `screen_size` too large | Out of memory | Keep under 500×500 for testing |
| Missing `sf_home` | Cache errors | Set to `"~/.simfire"` |
| `diagonal_spread: false` | Fire spreads slowly | Expected: only 4 neighbors vs 8 |

## Example

Minimal functional config for testing:

```yaml
area:
  screen_size: [100, 100]
  pixel_scale: 50
display:
  fire_size: 2
  control_line_size: 2
  agent_size: 4
simulation:
  update_rate: 1
  runtime: "1h"
  headless: true
  draw_spread_graph: false
  record: false
  save_data: true
  data_type: "npy"
  sf_home: "~/.simfire"
mitigation:
  ros_attenuation: true
terrain:
  topography:
    type: functional
    functional:
      function: flat
  fuel:
    type: functional
    functional:
      function: chaparral
      chaparral:
        seed: 42
fire:
  fire_initial_position:
    type: static
    static:
      position: (50, 50)
  max_fire_duration: 5
  diagonal_spread: true
environment:
  moisture: 0.03
wind:
  function: simple
  simple:
    speed: 880
    direction: 90.0
```
