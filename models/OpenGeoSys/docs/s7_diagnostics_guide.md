# Diagnostics Guide — Troubleshooting OGS Simulations

## Purpose

Systematic guide for diagnosing and fixing common OGS simulation failures. Organized by symptom category for rapid lookup during debugging.

## Inputs

- OGS log output (stdout/stderr)
- Output VTU files (if any were produced)
- Project file (.prj) being debugged

## Outputs

- Identified root cause
- Specific fix steps

## Procedure

### Category 1: Immediate Crashes (no output produced)

**Symptom**: OGS exits immediately with non-zero return code.

| Error Message | Root Cause | Fix |
|---------------|-----------|-----|
| "Could not read mesh" | Mesh file not found | Check `<mesh>` paths, use `-m` flag |
| "XML parse error" | Malformed .prj file | Run `xmllint --noout project.prj` |
| "Unknown process type" | Typo in `<type>` | Check against valid process types list |
| "SegFault" | Element order mismatch | Match `<order>` to actual mesh element order |
| "Required config ... not found" | Missing XML element | Check required elements for process type |
| "Could not find variable" | BC references undefined parameter | Verify all `<parameter>` names match references |

### Category 2: Non-Convergence (simulation stalls)

**Symptom**: OGS runs but reports "not converged" and reduces timestep repeatedly.

| Behavior | Likely Cause | Fix |
|----------|-------------|-----|
| Diverges from first iteration | Incompatible IC/BC | Check physical consistency of initial state |
| Converges then diverges | Timestep too large for nonlinearity | Reduce `delta_t` by 10× |
| Oscillating residual | Newton without line search | Switch to Picard or add damping |
| Converges slowly (>50 iterations) | Ill-conditioned system | Improve preconditioner, check permeability contrast |

### Category 3: Runs but Wrong Results (silent errors)

**Symptom**: Simulation completes, but output values are unphysical.

| Observation | Root Cause | Fix |
|-------------|-----------|-----|
| Pressure 1000× too low | Pressure in kPa not Pa | Multiply all pressures by 1000 |
| Temperature ~20 instead of ~293 | Temperature in °C not K | Add 273.15 to all temperatures |
| Flow 1e7× too fast | Ksat used as permeability | Multiply by μ/(ρg) ≈ 1.02e-7 |
| No temporal evolution | Storage = 0 | Set storage to ~1e-9 1/Pa |
| Simulation ends in 6 minutes | Time in days not seconds | Multiply by 86400 |
| Pressure uniform everywhere | Missing body force | Add `<specific_body_force>` |
| Recharge floods domain | mm/day not converted to m/s | Divide by 86,400,000 |

### Category 4: Numerical Artifacts

| Artifact | Cause | Fix |
|----------|-------|-----|
| Oscillating pressure at boundaries | Inconsistent BC/mesh | Refine mesh near BCs |
| Negative concentrations | Numerical dispersion | Reduce timestep or use upwinding |
| Checkerboard pattern | Wrong element type for pressure | Use Taylor-Hood elements for Stokes |
| Unrealistic velocity at corners | Singular point in mesh | Add local mesh refinement |

### Diagnostic Decision Tree

```
OGS exits immediately?
├── Yes → Check: XML valid? Mesh found? Process type spelled correctly?
└── No
    ├── Non-convergence?
    │   ├── From first step → Check: IC consistent? BC physical?
    │   └── After some steps → Reduce delta_t, switch to Picard
    └── Wrong results?
        ├── Values ~1000× off → Unit conversion error (see trap table)
        ├── No temporal change → Check storage > 0, time > 0
        └── Physically impossible → Check material properties, body force
```

## Verification

For any fix applied, verify:
- [ ] OGS completes without convergence warnings
- [ ] Output value ranges match expected physics
- [ ] Mass/energy balance is preserved (check in/out fluxes)

## Traps

This document references all 18 diagnostic triplets. The most dangerous are:
- **dt_003**: Permeability in Darcy or m/s instead of m² (silent, orders of magnitude error)
- **dt_002**: Temperature in °C instead of K (silent, wrong density/viscosity)
- **dt_009**: Storage = 0 in transient simulation (silent, no temporal evolution)
- **dt_011**: Hydraulic conductivity K used as intrinsic permeability κ (silent, 1e7× error)

## Example

Debugging a simulation where pressure doesn't change over time:

```bash
# Check 1: Is storage non-zero?
grep -A2 "storage" project.prj
# If <value>0</value> → change to <value>1e-9</value>

# Check 2: Is time long enough?
grep "t_end" project.prj
# If t_end=365 → change to 31536000 (365 days in seconds)

# Check 3: Is there a driving force?
grep "specific_body_force" project.prj
# If missing → add <specific_body_force>0 -9.81</specific_body_force>

# Re-run
ogs project.prj -o results/
```
