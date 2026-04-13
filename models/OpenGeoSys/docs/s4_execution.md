# Stage 4: Execution — Project File Assembly and OGS Run

## Purpose

Assemble the complete `.prj` project file from upstream stage outputs (mesh, BCs, material properties), configure the solver, execute OGS, and monitor for convergence.

## Inputs

- Mesh files: `domain.vtu`, `boundary_*.vtu`
- Material parameters (from Stage 3)
- Boundary condition data (from Stage 2)
- Process type and solver settings (from Stage 0)

## Outputs

- `project.prj` — Complete OGS project file (XML)
- `results/*.vtu` — VTK output files per timestep
- `results/*.pvd` — PVD time series index
- `run_summary.json` — Execution metrics and diagnostics

## Procedure

### Step 1: Assemble project file

The `.prj` file must contain these sections in order:

```xml
<?xml version="1.0" encoding="ISO-8859-1"?>
<OpenGeoSysProject>
  <meshes>...</meshes>           <!-- Step 1a -->
  <processes>...</processes>     <!-- Step 1b -->
  <media>...</media>             <!-- Step 1c -->
  <time_loop>...</time_loop>     <!-- Step 1d -->
  <parameters>...</parameters>   <!-- Step 1e -->
  <curves>...</curves>           <!-- Step 1f (optional) -->
  <process_variables>...</process_variables>  <!-- Step 1g -->
  <nonlinear_solvers>...</nonlinear_solvers>  <!-- Step 1h -->
  <linear_solvers>...</linear_solvers>        <!-- Step 1i -->
</OpenGeoSysProject>
```

### Step 1d: Time loop configuration

```xml
<time_loop>
  <processes>
    <process ref="LiquidFlow">
      <nonlinear_solver>basic_picard</nonlinear_solver>
      <convergence_criterion>
        <type>DeltaX</type>
        <norm_type>NORM2</norm_type>
        <abstol>1.e-6</abstol>
      </convergence_criterion>
      <time_discretization>
        <type>BackwardEuler</type>
      </time_discretization>
      <time_stepping>
        <type>FixedTimeStepping</type>
        <t_initial>0</t_initial>
        <t_end>31536000</t_end>  <!-- 1 year in seconds -->
        <timesteps>
          <pair><repeat>365</repeat><delta_t>86400</delta_t></pair>
        </timesteps>
      </time_stepping>
    </process>
  </processes>
  <output>
    <type>VTK</type>
    <prefix>result</prefix>
    <timesteps>
      <pair><repeat>1</repeat><each_steps>10</each_steps></pair>
    </timesteps>
    <variables>
      <variable>pressure</variable>
      <variable>v</variable>  <!-- Darcy velocity -->
    </variables>
    <suffix>_ts_{:timestep}_t_{:time}</suffix>
  </output>
</time_loop>
```

### Step 1h/1i: Solver configuration

**For small problems (< 100k DOFs)**:
```xml
<linear_solver>
  <name>general_linear_solver</name>
  <eigen>
    <solver_type>SparseLU</solver_type>
  </eigen>
</linear_solver>
```

**For larger problems**:
```xml
<linear_solver>
  <name>general_linear_solver</name>
  <eigen>
    <solver_type>BiCGSTAB</solver_type>
    <precon_type>ILUT</precon_type>
    <max_iteration_step>10000</max_iteration_step>
    <error_tolerance>1e-16</error_tolerance>
  </eigen>
</linear_solver>
```

### Step 2: Run OGS

```bash
# Direct execution
ogs project.prj -o results/

# Via wrapper tool (recommended)
python tools/run_ogs.py --prj project.prj --ogs_binary ./build/bin/ogs --output_dir results/
```

### Step 3: Monitor convergence

OGS logs show per-timestep iteration info:
```
=== Time stepping at step 42 and target time 3628800 with step size 86400
--- Picard nonlinear solver iteration #1 ---
  |dx|=1.234e-03, |x|=5.678e+05
--- Picard nonlinear solver iteration #2 ---
  |dx|=4.567e-07, |x|=5.678e+05
Convergence criterion fulfilled.
```

**Warning signs**:
- Iterations reaching `max_iter` → tighten timestep or loosen tolerance
- |dx| not decreasing → problem is ill-conditioned
- NaN in output → check material properties, BCs

### Step 4: Handle common failures

| Failure | Cause | Fix |
|---------|-------|-----|
| XML parse error | Malformed project file | Validate XML: `xmllint --noout project.prj` |
| Mesh file not found | Wrong path | Use `-m` flag for mesh directory |
| Non-convergence | Large timestep or stiff problem | Reduce delta_t by 10× |
| NaN in solution | Zero density/viscosity, missing BC | Check all material properties > 0 |
| Segfault | Element order mismatch | Match `<order>` to mesh element order |

## Verification

- [ ] `xmllint --noout project.prj` returns no errors
- [ ] All mesh files referenced in `<meshes>` exist
- [ ] Output directory exists or is created
- [ ] Test run with 2-3 timesteps completes without error
- [ ] Output VTU files contain expected variables

## Traps

| Trap | Severity | Prevention |
|------|----------|------------|
| XML tag misspelling (case-sensitive) | fatal | Use template, validate with xmllint |
| `t_end` in days not seconds | silent | Always multiply by 86400 |
| `<order>` mismatch with mesh | fatal | Linear mesh → order=1, quadratic → order=2 |
| Missing `<specific_body_force>` | silent | Always add for flow problems with gravity |
| Output prefix contains path separator | crash | Use flat name, set -o for directory |
| `each_steps` too large | silent | Missing timestep outputs |

## Example

Running the gravity-driven benchmark:

```bash
cd Tests/Data/Parabolic/LiquidFlow/GravityDriven/
ogs gravity_driven.prj -o output/

# Expected: 1 timestep, produces gravity_driven_ts_1_t_1.000000.vtu
# Contains: pressure field (hydrostatic) and Darcy velocity
```
