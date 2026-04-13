# S3: Initial and Boundary Conditions

## Purpose

Create ROMS initial condition (IC) and open boundary condition (OBC) NetCDF files
from global ocean model output (e.g., HYCOM, GLORYS, SODA, CMEMS). The IC provides
the starting state (T, S, velocity, sea level), and OBCs provide time-varying
data at open boundaries to prevent the regional domain from drifting.

## Inputs

| Input | Format | Source | Variables |
|-------|--------|--------|-----------|
| Global ocean data | NetCDF | HYCOM/GLORYS/SODA | temp, salt, ssh, u, v |
| ROMS grid file | NetCDF | S0 output | Grid geometry |
| Vertical parameters | From roms.in | S-coordinate config | Vtransform, Vstretching, THETA_S/B, TCLINE, N |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `roms_ini.nc` | NetCDF | Initial conditions: temp, salt, u, v, ubar, vbar, zeta |
| `roms_bry.nc` | NetCDF | Boundary conditions at each open edge |

## Procedure

### Step 1: Download global ocean data

For HYCOM (public):
```bash
# HYCOM GLBv0.08 (1/12° global)
wget "https://tds.hycom.org/thredds/dodsC/GLBv0.08/expt_93.0/ts3z"
```

For CMEMS/GLORYS:
```python
import copernicusmarine
copernicusmarine.subset(
    dataset_id="cmems_mod_glo_phy_my_0.083deg_P1D-m",
    variables=["thetao", "so", "uo", "vo", "zos"],
    minimum_longitude=-76, maximum_longitude=-70,
    minimum_latitude=35, maximum_latitude=42,
    start_datetime="2020-01-01", end_datetime="2020-02-01",
    output="glorys_2020jan.nc"
)
```

### Step 2: Horizontal interpolation

Interpolate global data (on z-levels) onto the ROMS horizontal grid.
Use bilinear interpolation. Take care with:
- **Staggering:** Temperature/salinity → RHO-points; u → U-points; v → V-points
- **Land masking:** Fill land values before interpolation (nearest-neighbor extrapolation)
- **Rotation:** If ROMS grid is rotated, rotate u/v to align with grid XI/ETA axes

### Step 3: Vertical interpolation

Convert from z-levels to ROMS S-coordinate levels:

1. Compute ROMS depth at each S-level using the S-coordinate formula:
   ```
   # Vtransform=2:
   z0 = (hc * s + h * Cs) / (hc + h)
   z = zeta + (zeta + h) * z0
   ```

2. Interpolate source data (on z-levels) to ROMS S-levels at each horizontal point.

3. Extrapolate below the deepest source level (use nearest-neighbor or constant).

**TRAP:** Getting the S-coordinate formula wrong produces garbage initial
conditions. Always verify the resulting temperature profile against the source.

### Step 4: Compute barotropic velocities

After interpolating 3D velocities to S-coordinates, compute depth-averaged
(barotropic) components:
```python
ubar = np.sum(u * dz, axis=0) / np.sum(dz, axis=0)
vbar = np.sum(v * dz, axis=0) / np.sum(dz, axis=0)
```

### Step 5: Create initial conditions file

Required variables:
- `ocean_time` — seconds since TIME_REF
- `zeta(time, eta_rho, xi_rho)` — sea surface height (m)
- `temp(time, s_rho, eta_rho, xi_rho)` — temperature (°C)
- `salt(time, s_rho, eta_rho, xi_rho)` — salinity (PSU)
- `u(time, s_rho, eta_u, xi_u)` — 3D XI-velocity (m/s)
- `v(time, s_rho, eta_v, xi_v)` — 3D ETA-velocity (m/s)
- `ubar(time, eta_u, xi_u)` — depth-averaged XI-velocity (m/s)
- `vbar(time, eta_v, xi_v)` — depth-averaged ETA-velocity (m/s)

### Step 6: Create boundary conditions file

For each open boundary (west/east/south/north), extract the edge slice:
- `temp_west(time, s_rho, eta_rho)` — temperature on west boundary
- `salt_east(time, s_rho, eta_rho)` — salinity on east boundary
- `zeta_south(time, xi_rho)` — SSH on south boundary
- etc.

The OBC file must cover the full simulation period with sufficient temporal
resolution (daily minimum, 6-hourly preferred for realistic runs).

### Step 7: Set boundary types in roms.in

```
LBC(isFsur) ==   Cha   Cla   Cha   Cla    ! free-surface
LBC(isUbar) ==   Fla   Fla   Fla   Fla    ! 2D u-momentum
LBC(isVbar) ==   Fla   Fla   Fla   Fla    ! 2D v-momentum
LBC(isUvel) ==   RadNud RadNud RadNud RadNud  ! 3D u-momentum
LBC(isVvel) ==   RadNud RadNud RadNud RadNud  ! 3D v-momentum
LBC(isTvar) ==   RadNud RadNud RadNud RadNud  ! temperature
                  RadNud RadNud RadNud RadNud  ! salinity
```

Set nudging time scales in `roms.in`:
```
Tnudg == 10.0  10.0    ! nudging time scale (days) for each tracer
```

## Verification

```python
# Compare IC profile against source at a test point
from netCDF4 import Dataset
import matplotlib.pyplot as plt

ini = Dataset('roms_ini.nc')
src = Dataset('glorys_source.nc')

# ROMS IC temperature profile at center
j, i = ini.variables['temp'].shape[2]//2, ini.variables['temp'].shape[3]//2
temp_roms = ini.variables['temp'][0, :, j, i]
# Source profile at same location
temp_src = src.variables['thetao'][0, :, 20, 20]

plt.plot(temp_src, -src.variables['depth'][:], 'k-', label='Source')
plt.plot(temp_roms, range(len(temp_roms)), 'b-', label='ROMS IC')
plt.legend()
plt.xlabel('Temperature (°C)')
plt.ylabel('Level')
plt.savefig('ic_profile_check.png')
```

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| Temperature in Kelvin | Source in K, ROMS expects °C | SILENT — wrong density, wrong circulation |
| Salinity units | Some sources use ‰ or g/L | Usually same as PSU but verify |
| S-coordinate mismatch | IC computed with wrong Vtransform/THETA | Distorted water column |
| Missing barotropic | ubar/vbar not computed from u/v | Inconsistent 2D/3D fields |
| Wrong time reference | IC time doesn't match roms.in TIME_REF | ROMS applies IC at wrong model time |
| Land fill gaps | Unfilled land creates NaN | Model blows up near coast |
| No vertical extrapolation | Deep S-levels below source data | NaN in deep ocean |

## Example

```bash
# Create initial conditions from GLORYS
python tools/convert_forcing.py \
  --mode initial \
  --source glorys_2020jan.nc \
  --grid roms_grid.nc \
  --output roms_ini.nc \
  --time-ref "2020-01-01" \
  --n-levels 30

# Create boundary conditions
python tools/convert_forcing.py \
  --mode boundary \
  --source glorys_2020jan.nc \
  --grid roms_grid.nc \
  --output roms_bry.nc \
  --time-ref "2020-01-01"
```
