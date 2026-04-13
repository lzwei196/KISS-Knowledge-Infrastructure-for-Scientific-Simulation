# S4: SIF Configuration

## Purpose

Assemble the Simulation Input File (SIF) — the master configuration file that
controls all aspects of an Elmer/Ice simulation. The SIF defines the mesh,
physics modules, material properties, boundary conditions, solver settings,
and output options.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Mesh directory | Stage s2 | Path to Elmer mesh files |
| Geometry files | Stage s1 | Node-indexed Zb, Zs, H data |
| Forcing files | Stage s3 | SMB, temperature, basal melt data |
| Physics choices | User | Which solvers to activate |
| Calibration parameters | User/inversion | Friction, viscosity, etc. |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `simulation.sif` | Elmer SIF text | Complete simulation configuration |
| `results.vtu` | VTU (produced by run) | Model output |

## Procedure

1. **Choose physics modules**: Select which solvers to include:
   - SSA (fast, depth-averaged) vs Full-Stokes (accurate, expensive)
   - Thermodynamics (Temperature or Enthalpy solver)
   - Hydrology (GlaDS if needed)
   - Thickness evolution (for transient runs)

2. **Generate SIF**:
   ```bash
   python generate_sif.py --mesh_dir rectangle --output simulation.sif \
       --coordinate_system "Cartesian 2D" --n_timesteps 100 --dt_years 1.0 \
       --glen_n 3.0 --friction_law weertman --friction_parameter 1e-3 \
       --ice_density 910 --smb_value 0.3 --initial_thickness 1000
   ```

3. **Review and customize**: The generated SIF is a starting point — add
   additional solvers, boundary conditions, or exported variables as needed.

4. **Validate**: Check for common traps before running.

## SIF Block Reference

### Header
```
Header
  Mesh DB "." "mesh_directory"
End
```

### Simulation
```
Simulation
  Coordinate System = Cartesian 2D    ! or Cartesian 3D
  Simulation Type = Transient         ! or Steady State
  Timestepping Method = "bdf"
  BDF Order = 1
  Timestep Intervals = 100            ! number of steps
  Timestep Sizes = 31556926.0         ! 1 year in SECONDS (dt_009!)
  Post File = "results.vtu"
  Output Intervals = 10
  Max Output Level = 5
End
```

### Constants
```
Constants
  Gas Constant = Real 8.314           ! J/(mol K)
  Sea Level = Real 0.0
  Water Density = Real 1025.0         ! kg/m3 (dt_003!)
End
```

### Material (SSA)
```
Material 1
  Viscosity Exponent = Real 0.333333  ! 1/n, NOT n! (dt_002!)
  Critical Shear Rate = Real 1.0e-10  ! MUST be > 0 (dt_013!)
  Density = Real 910.0                ! kg/m3 (dt_003!)
  SSA Friction Law = String "weertman"
  SSA Friction Parameter = Real 1.0e-3
  SSA Friction Exponent = Real 0.333333
  SSA Mean Density = Real 910.0
  SSA Mean Viscosity = Real 1.0e14    ! Pa s
End
```

### Solver (SSA)
```
Solver 1
  Equation = "SSA"
  Procedure = "ElmerIceSolvers" "SSABasalSolver"
  Variable = -dofs 1 "SSAVelocity"    ! 1 for flowline, 2 for plan-view
  Linear System Solver = Direct
  Linear System Direct Method = umfpack  ! mumps for parallel
  Nonlinear System Max Iterations = 50
  Nonlinear System Convergence Tolerance = 1.0e-6
End
```

## Verification

Before running, check:
- [ ] Viscosity Exponent < 1 (should be 1/n ≈ 0.333)
- [ ] Critical Shear Rate > 0
- [ ] Density in kg/m3 (hundreds, not < 10)
- [ ] Timestep Sizes in seconds (millions for annual)
- [ ] Coordinate System matches mesh dimension
- [ ] Mesh DB path is correct
- [ ] Boundary Condition targets match mesh boundary IDs

## Traps

| Trap | ID | Severity | Quick Check |
|------|----|----------|-------------|
| n vs 1/n | dt_002 | silent | Viscosity Exponent < 1? |
| kg/m3 vs g/cm3 | dt_003 | silent | Density > 100? |
| seconds vs years | dt_009 | silent | Timestep > 1e6? |
| Critical Shear Rate = 0 | dt_013 | fatal | Must be > 0 |
| Missing Body Force | dt_012 | silent | Block exists? |
| Wrong DOFs | dt_018 | fatal | SSA: 1 or 2; Fabric: 5 |
| Output Intervals | dt_015 | degraded | <= Timestep Intervals? |

## Example

```bash
# Generate SSA flowline SIF
python generate_sif.py --mesh_dir rectangle --output test.sif \
    --coordinate_system "Cartesian 2D" --n_timesteps 100 --dt_years 1.0 \
    --glen_n 3.0 --friction_law linear --friction_parameter 1e-3

# Steady-state 3D
python generate_sif.py --mesh_dir glacier3d --output steady.sif \
    --coordinate_system "Cartesian 3D" --n_timesteps 1 \
    --linear_solver Iterative --iterative_method BiCGStab
```
