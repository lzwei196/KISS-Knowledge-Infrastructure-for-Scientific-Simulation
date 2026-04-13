# S2: Parameter Configuration (fort.15)

## Purpose

Configure the ADCIRC control file (fort.15) which specifies all model parameters: timestep, physical constants, friction formulation, forcing options, output control, and boundary conditions. This is the most complex input file and the primary source of configuration errors.

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| Mesh info | fort.14 | — | Node count, element count, boundary count |
| Simulation period | User-defined | dates | Start time, end time, ramp period |
| Tidal constituents | TPXO, FES2014 | harmonic data | Amplitudes, phases for open boundaries |
| Physical settings | User-defined | — | Friction type, coordinate system, gravity |

## Outputs

| Output | File | Format | Description |
|--------|------|--------|-------------|
| Control file | `fort.15` | ASCII | Complete ADCIRC parameter specification |

## Procedure

### 1. Coordinate System and Constants

```
ICS = 2        ! 1=Cartesian, 2=Spherical (lat/lon in degrees)
IM = 0         ! 0=2D barotropic, 21=3D baroclinic
G = 9.81       ! Gravity (MUST be 9.81 for ICS=2, metric) (dt_002)
```

### 2. Time Stepping

```
DTDP = 2.0     ! Timestep in SECONDS (not hours!) (dt_006)
                ! CFL: DTDP < dx_min / sqrt(g * h_max)
STATIM = 0.0   ! Starting time in days (reference for output)
REFTIM = 0.0   ! Reference time in days
RNDAY = 30.0   ! Total run length in DAYS
DRAMP = 5.0    ! Ramp period in DAYS (gradually increase forcing)
```

### 3. Friction

```
NOLIBF = 1     ! 0=linear (TAU), 1=quadratic (CF), 2=hybrid
CF = 0.003     ! Quadratic friction coefficient (dimensionless)
                ! Or use fort.13 for spatially varying Manning's n
```

### 4. Meteorological Forcing

```
NWS = 12       ! Wind format: 0=none, 12=OWI, 8=Holland, etc.
                ! NWS>0 requires fort.22
WTIMINC = 900  ! Wind time increment in SECONDS
```

### 5. Tidal Forcing

```
NTIP = 1       ! 1=tidal potential, 2=SAL+tidal potential
NBFR = 8       ! Number of tidal constituents at open boundaries
                ! Then specify: name, period (s), nodal factor, eq arg
                ! For each: amplitude (m), phase (degrees) per boundary node
```

### 6. Wetting/Drying

```
NOLIFA = 2     ! 2=enable wetting/drying
H0 = 0.05      ! Dry threshold in METERS (dt_008)
VELMIN = 0.05  ! Minimum velocity for wetting (m/s)
```

### 7. Output Control

```
NOUTE = 1      ! Station elevation output: 0=off, 1=ASCII, 5=netCDF
NSPOOLE = 10   ! Decimation factor (output every N timesteps)
NSTAE = 5      ! Number of elevation recording stations
                ! Then: lat lon for each station

NOUTGE = 1     ! Global elevation output
NSPOOLGE = 360 ! Global output every 360 timesteps
```

### 8. GWCE Parameters

```
TAU0 = -3      ! GWCE weighting (-3=automatic spatially varying) (dt_005)
                ! Positive values: 0.005-0.1 (lower=more accurate, less stable)
```

### 9. Lateral Viscosity

```
ESLM = 10.0    ! Lateral viscosity (m²/s) for 2D
                ! Too small: oscillations. Too large: excessive damping.
```

## Verification

```bash
# Check timestep vs mesh resolution (CFL)
python3 -c "
import math
dx_min = 100    # meters (smallest element)
h_max = 50      # meters (max depth)
g = 9.81
cfl_max_dt = dx_min / math.sqrt(g * h_max)
print(f'CFL max DTDP: {cfl_max_dt:.2f} s')
"

# Verify total simulation steps
python3 -c "
rnday = 30; dtdp = 2.0
nsteps = int(rnday * 86400 / dtdp)
print(f'Total steps: {nsteps:,}')
"
```

## Traps

| Trap | ID | Symptom |
|------|----|---------|
| G=32.174 with ICS=2 | dt_002 | Completely wrong physics, no error message |
| DTDP violates CFL | dt_006 | Growing oscillations, eventual NaN |
| TAU0 too small | dt_005 | Mass balance errors, spurious oscillations |
| H0 too large | dt_008 | Inundation extent underestimated |
| ESLM too large | dt_016 | Over-damped velocity field, NaN possible |
| Time in wrong units | dt_015 | Simulation too short/long (days vs seconds) |

## Example

```
EC2015 ADCIRC Run                    ! RUNDES
Gulf Coast Storm Surge               ! RUNID
1                                    ! NFOVER
1                                    ! NABOUT
0                                    ! NSCREEN
0                                    ! IHOT (0=cold start, 67/68=hot start)
2                                    ! ICS (2=spherical)
0                                    ! IM (0=2DDI)
0                                    ! NOLIBF_COMPAT (not used)
1                                    ! NOLIBF (1=quadratic)
2                                    ! NOLIFA (2=wet/dry)
0 0                                  ! NOLICA NOLICAT
12                                   ! NWS (12=OWI)
1                                    ! NCOR (1=spatially varying Coriolis)
1                                    ! NTIP (1=tidal potential)
0                                    ! NWP (number of nodal attribute names)
1                                    ! NCICE
2.0                                  ! DTDP (seconds)
0.0                                  ! STATIM (days)
0.0                                  ! REFTIM (days)
30.0                                 ! RNDAY (days)
5.0                                  ! DRAMP (days)
0.35 0.30 0.35                       ! A00 B00 C00 (time weighting)
0.05 5 10                            ! H0 VELMIN NODEDRYMIN
-94.0 29.5                           ! SLAM0 SFEA0 (center of projection)
-3.0                                 ! TAU0 (GWCE, negative=auto)
0.003                                ! CF (quadratic friction)
10.0                                 ! ESLM (lateral viscosity m²/s)
0.0                                  ! CORI (not used when NCOR=1)
8                                    ! NBFR (tidal constituents)
...
```
