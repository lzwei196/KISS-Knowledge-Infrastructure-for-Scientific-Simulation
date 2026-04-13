# Stage 4: Channel Geometry and Routing Setup

## Purpose

Define the channel network geometry (width, bank angle, Manning's roughness,
sinuosity) that controls how water is routed through the D8 flow grid.
TopoFlow supports kinematic, diffusive, and dynamic wave approximations.

## Inputs

| Parameter       | Symbol  | Unit (TopoFlow) | Source                        |
|-----------------|---------|------------------|-------------------------------|
| Channel width   | w       | m                | Field data, power-law scaling |
| Bank angle      | angle   | degrees          | 0 = vertical, ~60 typical    |
| Manning's n     | n       | s/m^(1/3)        | Literature lookup by land use |
| Initial depth   | d0      | m                | Typically 0 or small value    |
| Sinuosity       | sinu    | —                | Length/straight-line (≥ 1.0)  |
| Bankfull depth  | d_bankfull | m             | Field or regional regression  |

## Outputs

| File                    | Format     | Description                              |
|-------------------------|------------|------------------------------------------|
| `*_chan-w.rtg`          | RTG binary | Channel width grid (m)                   |
| `*_chan-n.rtg`          | RTG binary | Manning's n grid (s/m^(1/3))             |
| `*_chan-angle.rtg`      | RTG binary | Bank angle grid (degrees)                |
| `*_chan-sinu.rtg`       | RTG binary | Sinuosity grid (—)                       |
| `*_d0.rtg`             | RTG binary | Initial flow depth (m)                   |
| `*_channels_*.cfg`      | CFG        | Channel routing configuration            |

## Procedure

### Step 1: Choose routing method

| Method           | When to Use                              | Stability           |
|------------------|------------------------------------------|----------------------|
| Kinematic Wave   | Steep slopes (> 0.001), most cases       | Most stable          |
| Diffusive Wave   | Mild slopes, backwater effects           | Moderate stability   |
| Dynamic Wave     | Very flat areas, tidal influence          | Least stable         |

For most applications, **kinematic wave** is recommended.

### Step 2: Derive channel width

For ungauged basins, use hydraulic geometry scaling:

```
w = a × A^b
```

where A is contributing area (km²), and typical values are a = 3–5, b = 0.4–0.5.

For the Treynor test case (small watershed), uniform width of 1–3 m is appropriate.

### Step 3: Set Manning's roughness

| Land Cover / Channel Type     | Manning's n         |
|-------------------------------|---------------------|
| Clean natural stream          | 0.025 – 0.033      |
| Weedy stream, some pools      | 0.030 – 0.050      |
| Heavy brush, timber           | 0.050 – 0.150      |
| Concrete-lined channel        | 0.013 – 0.015      |
| Overland flow (grass)         | 0.10 – 0.30        |
| Overland flow (bare soil)     | 0.01 – 0.03        |
| Floodplain (pasture)          | 0.030 – 0.040      |

**CRITICAL:** TopoFlow uses Manning's n, **not** 1/n.  If you accidentally
provide the reciprocal, velocities will be wildly wrong.

### Step 4: Configure bank angle and sinuosity

- **Bank angle:** 0° = vertical walls (simplest), 30–60° more realistic
- **Sinuosity:** Ratio of channel length to straight-line distance. 1.0 = straight,
  1.1–1.5 for meandering channels.

### Step 5: Select friction law

In the channels .cfg file:

```
MANNING          | 1           | int    | 1=Manning, 0=Law of Wall
```

For Manning's equation: Q = (1/n) × A × R^(2/3) × S^(1/2)

For Law of Wall: requires roughness length z0 instead of n.

### Step 6: Write channels .cfg

```
# channels_kinematic_wave.cfg
comp_status      | Enabled       | string  | component status
dt               | 6.0           | float   | timestep [sec]
MANNING          | 1             | int     | 1=Manning, 0=Law of Wall

code_type        | Grid          | string  | D8 flow code input type
code_file        | [site_prefix]_flow.rtg | string | D8 flow code file

slope_type       | Grid          | string  | slope input type
slope_file       | [site_prefix]_slope.rtg | string | slope file

width_type       | Scalar        | string  | channel width input type
width            | 3.0           | float   | channel width [m]

angle_type       | Scalar        | string  | bank angle type
angle            | 0.0           | float   | bank angle [deg] (0=vertical)

nval_type        | Scalar        | string  | Manning's n input type
nval             | 0.03          | float   | Manning's n [s/m^(1/3)]

d0_type          | Scalar        | string  | initial depth type
d0_val           | 0.0           | float   | initial flow depth [m]

sinu_type        | Scalar        | string  | sinuosity type
sinu_val         | 1.0           | float   | sinuosity [-]
```

## Verification

1. **Width > 0 everywhere:** Zero width causes division by zero.
2. **Manning's n in correct range:** 0.01–0.30 for channels, higher for overland.
3. **n is not inverted:** If n = 33.3, you used 1/n instead of n.
4. **Timestep CFL condition:** dt ≤ dx / v_max, where v_max ≈ (1/n) × R^(2/3) × S^(1/2).
   For a 30 m grid with slope 0.01 and n = 0.03, v_max ≈ 3 m/s → dt ≤ 10 s.
5. **Slope consistency:** Slope file must be derived from the same DEM as the D8 grid.

## Traps

| Trap                          | Symptom                               | Fix                              |
|-------------------------------|---------------------------------------|----------------------------------|
| Channel width = 0             | Division by zero, crash               | Ensure all cells w > 0          |
| Manning's n inverted (1/n)    | Velocities 1000× wrong               | Use n, not 1/n                  |
| Too-large timestep            | CFL violation, numerical oscillations | Reduce dt (try 2–6 sec)        |
| Slope and D8 from different DEMs | Inconsistent routing             | Derive both from same DEM      |
| Bank angle > 90°              | Negative top-width, crash             | Keep 0 ≤ angle < 90            |

## Example

Treynor Iowa kinematic wave setup:
- Width: 3.0 m (uniform, small agricultural catchment)
- Manning's n: 0.03 (clean natural stream)
- Bank angle: 0° (vertical, trapezoidal simplification)
- Sinuosity: 1.0 (short, straight channels)
- dt: 6 seconds (CFL-safe for 30 m grid)
