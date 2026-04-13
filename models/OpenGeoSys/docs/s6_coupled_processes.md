# Stage 6: Coupled Processes — Multi-Physics Simulation Strategies

## Purpose

Guide the setup of coupled THMC simulations in OGS. Multi-physics coupling introduces additional complexity in process variable management, convergence, and physical consistency. This document covers coupling schemes, staggered vs monolithic approaches, and common pitfalls.

## Inputs

- Single-physics configurations that need to be combined
- Coupling requirements (e.g., pressure affects deformation, temperature affects viscosity)
- Computational resources (memory, CPU cores)

## Outputs

- Coupled `.prj` file with multiple process variables
- Staggered or monolithic solver configuration
- Appropriate convergence criteria for each coupled variable

## Procedure

### Step 1: Choose coupling scheme

| Scheme | Description | When to use |
|--------|-------------|-------------|
| **Monolithic** | All variables in one system | Strong coupling, small problems |
| **Staggered** | Solve each variable sequentially | Weak coupling, large problems |

**Monolithic** (default for most OGS processes):
- Single large linear system containing all unknowns
- Preserves strong coupling between variables
- Requires more memory (larger matrix)
- Newton solver can handle nonlinear coupling

**Staggered** (for selected processes like HT):
```xml
<processes>
  <process>
    <name>HeatTransport</name>
    <type>HT</type>
    <coupling_scheme>
      <type>staggered</type>
      <!-- Two sub-processes solved in sequence -->
    </coupling_scheme>
  </process>
</processes>
```

### Step 2: Configure process variables for coupled problems

**Hydro-Mechanics** (HYDRO_MECHANICS):
```xml
<process>
  <type>HYDRO_MECHANICS</type>
  <process_variables>
    <pressure>pressure</pressure>
    <displacement>displacement</displacement>
  </process_variables>
  <constitutive_relation>
    <type>LinearElasticIsotropic</type>
    <youngs_modulus>E</youngs_modulus>
    <poissons_ratio>nu</poissons_ratio>
  </constitutive_relation>
  <specific_body_force>0 -9.81</specific_body_force>
</process>
```

**Thermo-Richards-Mechanics** (TRM — most complex standard process):
```xml
<process>
  <type>THERMO_RICHARDS_MECHANICS</type>
  <process_variables>
    <temperature>temperature</temperature>
    <pressure>pressure</pressure>
    <displacement>displacement</displacement>
  </process_variables>
</process>
```

### Step 3: Set convergence criteria per variable

Different variables have different scales — use appropriate tolerances:

| Variable | Typical tolerance | Criterion type |
|----------|------------------|----------------|
| Pressure (Pa) | abstol=1e-6 | DeltaX |
| Temperature (K) | abstol=1e-4 | DeltaX |
| Displacement (m) | abstol=1e-10 | DeltaX |
| Concentration (mol/m³) | reltol=1e-6 | DeltaX |

For staggered coupling, add an outer (coupling) iteration loop:
```xml
<global_process_coupling>
  <max_iter>10</max_iter>
  <convergence_criteria>
    <convergence_criterion>
      <type>DeltaX</type>
      <norm_type>NORM2</norm_type>
      <abstol>1e-6</abstol>
    </convergence_criterion>
  </convergence_criteria>
</global_process_coupling>
```

### Step 4: Additional parameters for coupled processes

**Biot coefficient** (HydroMechanics):
```xml
<property><name>biot_coefficient</name><type>Constant</type><value>0.8</value></property>
```

**Thermal expansion** (ThermoMechanics):
```xml
<property><name>thermal_expansivity</name><type>Constant</type><value>1e-5</value></property>
```

### Step 5: Verify coupling consistency

Cross-check that:
- Same material properties used in all coupled processes
- Temperature-dependent properties update correctly between coupling steps
- Initial conditions are physically consistent across all variables
- Boundary conditions don't create unphysical forcing

## Verification

- [ ] All coupled process variables have initial conditions
- [ ] Convergence criteria set for each variable independently
- [ ] Coupling iteration limit set (staggered scheme)
- [ ] Material properties consistent across all phases/processes
- [ ] Body force vector present and correct for all relevant processes

## Traps

| Trap | Consequence | Prevention |
|------|-------------|------------|
| Missing initial condition for coupled variable | Crash or zero field | Set IC for every process variable |
| Same tolerance for pressure and displacement | One variable under-resolved | Scale tolerance to variable magnitude |
| No coupling iterations (staggered) | Operator splitting error | Set max_iter > 1 |
| Inconsistent thermal expansion | Artificial stress | Use consistent coefficient in all media |
| Monolithic for large 3D HM | Out of memory | Switch to staggered or PETSc |

## Example

Setting up a simple 2D thermo-hydraulic (HT) problem:

```xml
<processes>
  <process>
    <name>HeatTransport</name>
    <type>HT</type>
    <process_variables>
      <temperature>temperature</temperature>
      <pressure>pressure</pressure>
    </process_variables>
    <specific_body_force>0 -9.81</specific_body_force>
  </process>
</processes>

<!-- Initial conditions -->
<process_variables>
  <process_variable>
    <name>temperature</name>
    <components>1</components>
    <order>1</order>
    <initial_condition>T0</initial_condition>  <!-- 283.15 K = 10°C -->
  </process_variable>
  <process_variable>
    <name>pressure</name>
    <components>1</components>
    <order>1</order>
    <initial_condition>p0</initial_condition>  <!-- hydrostatic -->
  </process_variable>
</process_variables>
```
