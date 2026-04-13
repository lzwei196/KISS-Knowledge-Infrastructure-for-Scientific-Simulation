# S4: Steering File Configuration

## Purpose

Write the TELEMAC steering file (.cas) that specifies all simulation parameters:
input/output files, physical options, numerical scheme, time stepping, initial
and boundary conditions, and output control.

## Inputs

| Input                | Format   | Description                                 |
|----------------------|----------|---------------------------------------------|
| Geometry file        | .slf     | Mesh with bathymetry                        |
| Boundary file        | .cli     | Boundary condition types                    |
| Forcing files        | .txt/.slf| From Stage 3                                |
| Physical parameters  | Numeric  | Friction, viscosity, Coriolis, etc.         |
| Simulation period    | Numeric  | Time step and number of steps               |

## Outputs

| Output               | Format   | Description                                 |
|----------------------|----------|---------------------------------------------|
| Steering file        | .cas     | Complete simulation configuration           |

## Procedure

1. **Set file paths** (required keywords):
   ```
   GEOMETRY FILE            = geo.slf
   BOUNDARY CONDITIONS FILE = geo.cli
   RESULTS FILE             = results.slf
   ```

2. **Configure time stepping**:
   ```
   TIME STEP          = 1.0        / seconds
   NUMBER OF TIME STEPS = 36000   / total simulation time = 36000 s = 10 hr
   / OR use DURATION = 36000.
   ```
   Rule of thumb: dt < dx_min / (sqrt(g * h_max) + U_max) for CFL < 1.

3. **Select physical options**:
   ```
   EQUATIONS = 'SAINT-VENANT FE'   / or 'SAINT-VENANT FV' or 'BOUSSINESQ'
   LAW OF BOTTOM FRICTION = 4      / 0=none, 2=Chezy, 3=Strickler, 4=Manning
   FRICTION COEFFICIENT   = 0.025  / Manning n (s/m^1/3)
   TURBULENCE MODEL       = 1      / 1=constant visc, 3=K-epsilon, 4=Smagorinsky
   VELOCITY DIFFUSIVITY   = 1.0    / m^2/s (for model=1)
   ```

4. **Set boundary conditions**:
   ```
   PRESCRIBED FLOWRATES   = 0.;150.0   / per liquid boundary
   PRESCRIBED ELEVATIONS  = 2.5;0.     / per liquid boundary
   ```

5. **Configure output**:
   ```
   VARIABLES FOR GRAPHIC PRINTOUTS = 'U,V,H,S,B,F'
   GRAPHIC PRINTOUT PERIOD         = 100
   LISTING PRINTOUT PERIOD         = 50
   MASS-BALANCE                    = YES
   ```

6. **Numerical parameters**:
   ```
   SOLVER                     = 1    / 1=conjugate gradient
   SOLVER ACCURACY            = 1.E-5
   IMPLICITATION FOR DEPTH    = 0.6
   IMPLICITATION FOR VELOCITY = 0.6
   TIDAL FLATS                = YES  / enable wetting/drying
   TREATMENT OF NEGATIVE DEPTHS = 2  / conservative treatment
   ```

## Verification

- [ ] All referenced files exist in the working directory
- [ ] TIME STEP satisfies CFL condition
- [ ] FRICTION COEFFICIENT matches LAW OF BOTTOM FRICTION (Manning vs Strickler)
- [ ] Boundary counts match .cli file
- [ ] RESULTS FILE path is writable
- [ ] Output frequency is reasonable (not every timestep for long runs)

## Traps

- **dt_002**: Manning coefficient used with Strickler law (or vice versa).
  Manning n ~ 0.01-0.10. Strickler K = 1/n ~ 10-100.
- **dt_009**: Time step in minutes instead of seconds (60x error).
- **dt_014**: Missing TIDAL FLATS = YES for coastal simulations causes
  negative depths and numerical instability.
- **dt_015**: Time step too large for mesh resolution violates CFL.

## Example

```
/ TELEMAC-2D Steering File: Estuary simulation
/
TITLE = 'Estuary tidal flow'
/
/ Files
GEOMETRY FILE            = mesh_estuary.slf
BOUNDARY CONDITIONS FILE = mesh_estuary.cli
RESULTS FILE             = r2d_estuary.slf
LIQUID BOUNDARIES FILE   = tidal_bc.txt
/
/ Time
TIME STEP          = 2.0
NUMBER OF TIME STEPS = 21600     / 12 hours
/
/ Physics
EQUATIONS = 'SAINT-VENANT FE'
LAW OF BOTTOM FRICTION = 4
FRICTION COEFFICIENT   = 0.025
GRAVITY ACCELERATION   = 9.81
TIDAL FLATS            = YES
/
/ Output
VARIABLES FOR GRAPHIC PRINTOUTS = 'U,V,H,S,B,F'
GRAPHIC PRINTOUT PERIOD = 450    / every 15 minutes
MASS-BALANCE            = YES
```
