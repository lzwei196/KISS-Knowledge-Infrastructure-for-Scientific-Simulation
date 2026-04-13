# S4: Ocean Forcing — Ocean Boundary Conditions

## Purpose

Configure ocean boundary conditions that control sub-ice-shelf melting, sea level,
and thermal forcing at the grounding line. Ocean forcing is critical for marine ice
sheet dynamics and calving behavior.

## Inputs

| Source | Variables | Description |
|--------|-----------|-------------|
| Ocean temperature | θ (potential temp) | Continental shelf water properties |
| Ocean salinity | S | Salinity at ice-ocean interface |
| Sea level history | δSL | Relative sea level time series |
| Melt rate observations | m_dot | Sub-shelf melt rate (m/year) |

## Outputs

| Output | Units | PISM Variable |
|--------|-------|---------------|
| Sub-shelf melt rate | m year^-1 | `shelfbmassflux` |
| Sub-shelf temperature | kelvin | `shelfbtemp` |
| Sea level offset | m | `delta_SL` |

## Procedure

### Step 1: Choose Ocean Model

| Model | Flag | Description |
|-------|------|-------------|
| `constant` | `-ocean constant` | Uniform melt rate everywhere |
| `pico` | `-ocean pico` | PICO box model (Reese et al. 2018) |
| `th` | `-ocean th` | Three-equation plume model |
| `given` | `-ocean given` | Prescribed melt rate field |

### Step 2: Constant Ocean Model (simplest)

```bash
pism ... -ocean constant \
  -ocean.constant.melt_rate 5.0    # m/year (positive = melting)
```

**TRAP**: Melt rate is in m/year of ice equivalent. If your source data is in
m/day, multiply by 365.25. If in kg/m²/s, divide by ice density (910) and
multiply by seconds/year (31557600).

### Step 3: PICO Ocean Model (recommended for Antarctic)

```bash
pism ... -ocean pico \
  -ocean_pico_file ocean_forcing.nc
```

Required in `ocean_forcing.nc`:
- `theta_ocean`: Potential temperature (°C) on continental shelf
- `salinity_ocean`: Salinity (PSU) on continental shelf

PICO parameters:
```bash
-ocean.pico.number_of_boxes 5           # Number of overturning boxes
-ocean.pico.overturning_coefficient 1e6  # Overturning strength (m^6 s^-1 kg^-1)
-ocean.pico.heat_exchange_coefficent 5e-5  # Heat exchange (m/s)
-ocean.pico.continental_shelf_depth -2000  # Shelf break depth (m)
```

### Step 4: Sea Level Forcing

```bash
# Constant + delta_SL modifier
pism ... -sea_level constant,delta_sl \
  -ocean_delta_sl_file pism_dSL.nc
```

Required in `pism_dSL.nc`:
- `delta_SL(time)`: Sea level offset in meters
- `time`: Time coordinate with correct units and calendar

### Step 5: Calving Configuration

```bash
# Common calving combination for Greenland
pism ... \
  -calving eigen_calving,thickness_calving \
  -calving.eigen_calving.K 1e17 \
  -calving.thickness_calving.threshold 50 \
  -front_retreat_file bootstrap.nc
```

Calving models:
| Model | Flag | Key Parameter |
|-------|------|---------------|
| Eigen calving | `eigen_calving` | `-calving.eigen_calving.K` (m s) |
| Thickness calving | `thickness_calving` | `-calving.thickness_calving.threshold` (m) |
| von Mises calving | `vonmises_calving` | `-calving.vonmises_calving.sigma_max` (Pa) |
| Hayhurst calving | `hayhurst_calving` | Material damage parameter |
| Float kill | `float_kill` | Remove all floating ice |

## Verification

```bash
# Check melt rates in output
python3 -c "
from netCDF4 import Dataset
ds = Dataset('output.nc')
if 'bmelt' in ds.variables:
    bm = ds.variables['bmelt'][:]
    print(f'Basal melt: min={bm.min():.3f}, max={bm.max():.3f} m/year')
ds.close()
"
```

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Melt rate in m/day not m/year | SILENT | 365× too much melting → all ice shelves disappear |
| Ocean temp in kelvin not °C | SILENT | PICO expects °C for theta_ocean |
| Missing sea level file | DEGRADED | Sea level stays at 0 m |
| Calving K too high | SILENT | No calving → unrealistic ice shelf extent |
| Calving K too low | SILENT | Excessive calving → ice-free coast |

## Example

```bash
# Antarctic setup with PICO ocean model
mpiexec -n 64 pism \
  -i antarctica_bootstrap.nc -bootstrap \
  -ocean pico -ocean_pico_file ocean_forcing.nc \
  -calving eigen_calving,thickness_calving \
  -calving.eigen_calving.K 1e17 \
  -calving.thickness_calving.threshold 50 \
  -y 10000 -o antarctica_output.nc
```
