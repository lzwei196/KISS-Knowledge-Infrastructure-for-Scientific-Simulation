# S2: Boundary Conditions and Forcing

## Purpose

Define initial and boundary conditions for all field variables. Convert
external forcing data (discharge measurements, pressure readings, velocity
profiles) into OpenFOAM field file format with correct units and dimensions.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Velocity data | Measurement / design | CSV with Ux,Uy,Uz | m/s |
| Pressure data | Measurement | CSV with p | Pa (converted to m^2/s^2) |
| Discharge data | Gauge measurement | CSV with Q | m^3/s (converted to m/s) |
| Inlet area | Mesh geometry | Scalar | m^2 |
| Fluid density | physicalProperties | Scalar | kg/m^3 |
| Turbulence parameters | Estimation | k, epsilon, omega | m^2/s^2, m^2/s^3 |

## Outputs

| Output | Location | Format |
|--------|----------|--------|
| Velocity field | 0/U | OpenFOAM volVectorField |
| Pressure field | 0/p | OpenFOAM volScalarField |
| Turbulence fields | 0/k, 0/epsilon, 0/omega | OpenFOAM volScalarField |
| Phase fraction | 0/alpha.water (VoF) | OpenFOAM volScalarField |

## Procedure

### 1. Determine required fields

| Solver | Required Fields | Optional |
|--------|----------------|----------|
| incompressibleFluid (laminar) | p, U | - |
| incompressibleFluid (k-epsilon) | p, U, k, epsilon, nut | - |
| incompressibleFluid (k-omega SST) | p, U, k, omega, nut | - |
| incompressibleVoF | p_rgh, U, alpha.water | k, epsilon |
| fluid | p, U, T | k, epsilon |

### 2. Convert units

**Pressure (CRITICAL):**
```
p_openfoam [m^2/s^2] = p_measured [Pa] / rho [kg/m^3]
```
For water (rho=998): 101325 Pa -> 101.5 m^2/s^2

**Discharge to velocity:**
```
U [m/s] = Q [m^3/s] / A_inlet [m^2]
```
Assumes uniform velocity profile. For developed flow, use parabolic profile.

**Turbulence estimation:**
```
k = 1.5 * (U * TI)^2           [m^2/s^2]
epsilon = C_mu^0.75 * k^1.5 / l [m^2/s^3]
omega = k^0.5 / (C_mu^0.25 * l) [1/s]

where TI = turbulence intensity (0.01-0.10)
      l  = turbulence length scale (0.07 * D_hydraulic)
      C_mu = 0.09
```

### 3. Write field files

```bash
python convert_forcing_to_openfoam.py \
    --forcing-csv discharge.csv \
    --variable discharge \
    --inlet-area 0.01 \
    --inlet-patch inlet \
    --case-dir ./myCase
```

### 4. Set boundary condition types

| Patch | p | U | k/epsilon |
|-------|---|---|-----------|
| Inlet | zeroGradient | fixedValue | fixedValue |
| Outlet | fixedValue (0) | zeroGradient | zeroGradient |
| Wall | fixedFluxPressure | noSlip | wallFunction |
| Symmetry | symmetry | symmetry | symmetry |
| 2D front/back | empty | empty | empty |

## Verification

1. Patch names in all field files match polyMesh/boundary
2. Dimension arrays are correct for solver type
3. Vector fields have vector values `(Ux Uy Uz)`, not scalars
4. internalField is initialized (not left as uniform 0 for all fields)
5. Run `check_case.py` to validate patch consistency

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| Dynamic pressure in Pa | Dimension mismatch crash | Divide by density for incompressible |
| Scalar 0 for vector field | Parse error at startup | Use `uniform (0 0 0)` for vectors |
| Missing patches | "patch not found" fatal error | Check against polyMesh/boundary |
| Wrong turbulence init | Divergence in first iterations | Use estimation formulas above |
| fixedValue on outlet p | May cause mass imbalance | Use zeroGradient or totalPressure |
| Discharge not divided by area | Velocity = flow rate (far too large) | Always convert Q -> U = Q/A |

## Example

Set up boundary conditions for pipe flow with k-epsilon turbulence:

```bash
# Convert measured discharge to velocity BC
python convert_forcing_to_openfoam.py \
    --forcing-csv pipe_discharge.csv \
    --variable discharge \
    --inlet-area 0.00785 \
    --inlet-patch inlet \
    --density 998 \
    --case-dir ./pipeFlow

# Set physical properties
python convert_properties_to_openfoam.py \
    --case-dir ./pipeFlow \
    --fluid water \
    --turbulence-model kEpsilon
```

For Re = 10000, D = 0.1 m, U = 0.1 m/s:
- k = 1.5 * (0.1 * 0.05)^2 = 3.75e-5 m^2/s^2
- epsilon = 0.09^0.75 * 3.75e-5^1.5 / 0.007 = 1.04e-6 m^2/s^3
