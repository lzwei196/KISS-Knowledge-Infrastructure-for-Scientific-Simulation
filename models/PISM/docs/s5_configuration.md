# S5: Configuration — Physics and Solver Setup

## Purpose

Select and configure PISM's physics modules: stress balance, thermodynamics, basal
hydrology, bed deformation, and rheology. The configuration determines the physical
fidelity and computational cost of the simulation.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Physics choices | User decision | Which stress balance, surface model, etc. |
| Override config file | Optional NetCDF | Custom parameter values |
| Literature values | Publications | Calibrated parameters for region |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Command-line flags | CLI string | Complete PISM invocation |
| Config override file | NetCDF (.nc) | Custom pism_config.nc |

## Procedure

### Step 1: Choose Stress Balance

| Model | Flag | Use When |
|-------|------|----------|
| SIA only | (default) | Interior ice sheet, no sliding |
| SSA+SIA hybrid | `-stress_balance ssa+sia` | Sliding, ice streams, shelves |
| Blatter | `-stress_balance blatter` | Higher-order, steep topography |

For realistic ice sheet simulations, hybrid (SSA+SIA) is standard:
```bash
pism ... -stress_balance ssa+sia \
  -sia_e 3.0 \              # SIA enhancement factor
  -ssa_e 1.0 \              # SSA enhancement factor
  -pseudo_plastic \          # Pseudo-plastic sliding law
  -pseudo_plastic_q 0.25 \  # Sliding exponent (0=plastic, 1=linear)
  -till_effective_fraction_overburden 0.02
```

### Step 2: Configure Basal Strength

Till friction angle parameterization maps bedrock elevation to friction angle:
```bash
-topg_to_phi \
  -phi_min 15.0 \    # Minimum friction angle (degrees)
  -phi_max 40.0 \    # Maximum friction angle (degrees)
  -topg_min -300.0 \ # Bed elevation for phi_min (m)
  -topg_max 700.0    # Bed elevation for phi_max (m)
```

Low bed → low friction (marine sediments) → fast sliding
High bed → high friction (crystalline rock) → slow sliding

Sub-grid grounding line treatment:
```bash
-subgl                           # Sub-grid grounding line interpolation
-tauc_slippery_grounding_lines   # Reduce tauc at grounding line
```

### Step 3: Configure Energy Model

```bash
# Polythermal enthalpy model (default, recommended)
-energy enthalpy

# Cold ice approximation (faster, less accurate)
-energy cold

# No energy computation
-energy none
```

### Step 4: Configure Bed Deformation

```bash
# Lingle-Clark model (recommended for ice sheets)
-bed_def lc

# No bed deformation
-bed_def none

# Prescribed bed changes
-bed_def given -bed_def_given_file bed_changes.nc
```

### Step 5: Configure Hydrology

```bash
# Null transport (default) — no water routing
-hydrology null

# Distributed model — explicit water transport
-hydrology distributed

# Steady-state — diagnostic routing
-hydrology steady
```

### Step 6: Create Config Override File (Optional)

```bash
cat > my_config.cdl << 'EOF'
netcdf my_config {
    variables:
    byte pism_config;
    pism_config:constants.ice.density = 917.0;
    pism_config:constants.ice.density_type = "number";
    pism_config:constants.ice.density_units = "kg meter^-3";

    pism_config:surface.pdd.factor_ice = 0.008;
    pism_config:surface.pdd.factor_ice_type = "number";
    pism_config:surface.pdd.factor_ice_units = "m day^-1 kelvin^-1";

    pism_config:surface.pdd.factor_snow = 0.003;
    pism_config:surface.pdd.factor_snow_type = "number";
    pism_config:surface.pdd.factor_snow_units = "m day^-1 kelvin^-1";
}
EOF

ncgen -o my_config.nc my_config.cdl
pism ... -config_override my_config.nc
```

### Step 7: PIK Physics Extensions

```bash
-pik    # Enable PIK ice shelf extensions:
        #   - sub-grid grounding line
        #   - improved calving
        #   - kill icebergs
        #   - surface gradient inward at calving fronts
```

## Verification

```bash
# List all diagnostics available with current configuration
pism -i input.nc -bootstrap -list_diagnostics all

# Check which parameters differ from defaults
# (Parameters set by user are logged at startup)
```

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| sia_e too high (>5) | DEGRADED | Unrealistically fast ice flow |
| sia_e too low (<1) | DEGRADED | Ice sheet too thick/slow |
| PPQ=0 with no topg_to_phi | SILENT | All basal yield stress = 0 → infinite sliding |
| SSA without -pseudo_plastic | DEGRADED | Linear sliding — unrealistic |
| Lz < max ice thickness | FATAL | Ice exceeds domain → crash |
| Energy=none for long runs | SILENT | No thermodynamics → wrong rheology |

## Example

```bash
# Full Greenland configuration
mpiexec -n 16 pism \
  -i pism_Greenland.nc -bootstrap \
  -dx 10km -dy 10km -Mz 201 -Lz 4000 -Mbz 21 -Lbz 2000 \
  -stress_balance ssa+sia \
  -sia_e 3.0 -pseudo_plastic -pseudo_plastic_q 0.25 \
  -till_effective_fraction_overburden 0.02 \
  -topg_to_phi -phi_min 15.0 -phi_max 40.0 -topg_min -300.0 -topg_max 700.0 \
  -subgl -tauc_slippery_grounding_lines \
  -bed_def lc \
  -pik \
  -y 20000 -o greenland_spinup.nc
```
