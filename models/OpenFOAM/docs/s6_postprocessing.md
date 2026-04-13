# S6: Post-Processing and Output Analysis

## Purpose

Extract, analyze, and visualize simulation results. Convert OpenFOAM's
native field format to standard formats (CSV, VTK) for analysis and
comparison with measured data.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Time directories | Solver output | Field files (p, U, etc.) |
| Solver log | Execution | Text file |
| Function objects | postProcessing/ | dat/CSV files |
| Observed data | Measurement | CSV |

## Outputs

| Output | Format | Purpose |
|--------|--------|---------|
| Residual CSV | time,initial,final,iterations | Convergence analysis |
| Field statistics CSV | time,mean,min,max | Time series |
| Courant CSV | time,mean,max | Stability monitoring |
| VTK files | .vtk | ParaView visualization |
| Validation plots | PNG | Comparison with observations |

## Procedure

### 1. Extract residual convergence

```bash
python parse_openfoam_output.py \
    --case-dir ./myCase \
    --log-file log.foamRun \
    --extract-residuals \
    --csv-dir ./output
```

### 2. Extract field statistics

```bash
python parse_openfoam_output.py \
    --case-dir ./myCase \
    --extract-fields U,p,k \
    --csv-dir ./output
```

### 3. Convert to VTK

```bash
foamToVTK -case ./myCase
# Creates VTK/ directory with .vtk files per time step
```

### 4. Built-in function objects

Add to controlDict `functions{}` block:

```cpp
// Pressure/velocity probes
probes
{
    type            probes;
    libs            ("libsampling.so");
    writeControl    timeStep;
    writeInterval   1;
    probeLocations
    (
        (0.05 0.05 0.005)
        (0.08 0.08 0.005)
    );
    fields (p U);
}

// Forces on a patch
forces
{
    type            forces;
    libs            ("libforces.so");
    writeControl    timeStep;
    writeInterval   10;
    patches         (wall);
    rho             rhoInf;
    rhoInf          998;
    CofR            (0 0 0);
}

// Flow rate through a patch
flowRate
{
    type            surfaceFieldValue;
    libs            ("libfieldFunctionObjects.so");
    writeControl    timeStep;
    writeInterval   1;
    operation       sum;
    regionType      patch;
    name            outlet;
    fields          (phi);
}
```

### 5. Sampling along lines/planes

```bash
# Use postProcess utility
foamPostProcess -func "sample(start=(0 0 0.005), end=(0.1 0 0.005), nPoints=100, fields=(U p))"

# Or define in system/functions:
sample
{
    type            sets;
    libs            ("libsampling.so");
    writeControl    writeTime;
    sets
    (
        centerline
        {
            type        lineCell;
            axis        x;
            start       (0 0.05 0.005);
            end         (0.1 0.05 0.005);
        }
    );
    fields (U p);
}
```

### 6. Key metrics for hydraulics

| Metric | Formula | Use |
|--------|---------|-----|
| Flow rate | Q = sum(phi) on patch | Mass conservation check |
| Mean velocity | U_mean = Q / A | Flow characterization |
| Pressure drop | dp = p_inlet - p_outlet | Head loss calculation |
| Wall shear stress | tau_w = mu * dU/dy at wall | Friction factor |
| Froude number | Fr = U / sqrt(g * h) | Free surface flow regime |
| Head loss coefficient | K = dp / (0.5 * rho * U^2) | Component characterization |

### 7. Pressure unit conversion for reporting

**CRITICAL**: OpenFOAM incompressible pressure is kinematic (m^2/s^2).
Convert to engineering units:

```
p_Pa = p_OpenFOAM * rho           [Pa]
p_kPa = p_OpenFOAM * rho / 1000   [kPa]
p_mH2O = p_OpenFOAM / g           [meters of water]
```

## Verification

1. Residuals converged to specified tolerance
2. Mass balance: inlet flow rate = outlet flow rate (within tolerance)
3. Results physically reasonable (no negative pressures where unexpected)
4. Mesh independence: compare coarse vs fine mesh results
5. Comparison with analytical solution (where available) or published data

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| Reporting kinematic p as Pa | Pressure values seem ~1000x too small | Multiply by density |
| Reading binary field as ASCII | Garbled values | Check writeFormat in controlDict |
| Probe outside domain | Missing probe data | Verify probe point inside mesh bounds |
| purgeWrite deleted data | Missing time directories | Set purgeWrite 0 or save important times |
| phi (flux) vs U (velocity) | Confusing volumetric flux with velocity | phi is face-area-weighted, U is cell-center |

## Example

Full post-processing workflow:

```bash
# 1. Extract convergence history
python parse_openfoam_output.py \
    --case-dir ./cavity \
    --log-file log.foamRun \
    --extract-residuals \
    --extract-fields U,p \
    --csv-dir ./results

# 2. Convert for ParaView
foamToVTK -case ./cavity

# 3. Plot residuals
python3 -c "
import matplotlib.pyplot as plt
import csv
with open('results/residuals_Ux.csv') as f:
    r = list(csv.DictReader(f))
plt.semilogy([float(x['time']) for x in r], [float(x['final']) for x in r])
plt.xlabel('Time [s]'); plt.ylabel('Residual')
plt.savefig('residuals.png')
"
```
