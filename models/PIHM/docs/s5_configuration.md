# S5: Parameter Configuration Skill

## Purpose

Configure the PIHM `.para` (control parameters) and `.calib` (calibration
multipliers) files that control simulation behavior, solver settings, output
options, and parameter adjustments. Correct configuration prevents solver crashes,
excessive output, and mass balance errors.

## Prerequisites

- All input files prepared (S1–S4, S6)
- Simulation period defined
- Desired output variables and intervals identified

## Inputs

| Input | Description |
|-------|-------------|
| Simulation period | Start and end dates |
| Time step | Model step size in seconds |
| Output variables | Which variables to save and at what interval |
| Calibration parameters | Multipliers for soil/river/vegetation properties |

## Outputs

| Output | Path | Format |
|--------|------|--------|
| Control parameters | `input/<project>/<project>.para` | PIHM text |
| Calibration file | `input/<project>/<project>.calib` | PIHM text |

## Procedure

### Step 1: Configure .para File

#### Simulation Mode
```
SIMULATION_MODE    0    # 0=normal, 1=spin-up
INIT_MODE          0    # 0=relaxation (default IC), 1=use .ic file
```

- First run: use `SIMULATION_MODE=1` for spin-up
- Production run: use `SIMULATION_MODE=0, INIT_MODE=1`

#### Time Window
```
START    2009-01-01 00:00
END      2009-12-31 23:00
```

#### Time Steps
```
MODEL_STEPSIZE    60       # Hydrology step (seconds) — typically 60
LSM_STEP          900      # Land surface step (seconds) — typically 900
```

- MODEL_STEPSIZE is the outer loop step; CVODE adaptively sub-steps within
- Smaller steps = more stable but slower
- For steep/flashy catchments, try 30 seconds

#### CVODE Solver Settings
```
ABSTOL              1.0E-04    # Absolute tolerance (m) — controls mass conservation
RELTOL              1.0E-03    # Relative tolerance (dimensionless)
INIT_SOLVER_STEP    5.0E-03    # Initial CVODE step (seconds)
MAX_SOLVER_STEP     60         # Maximum CVODE step (seconds)
NUM_NONCOV_FAIL     0          # Non-convergence failures before reducing step
MAX_NONLIN_ITER     3          # Maximum nonlinear iterations
MIN_NONLIN_ITER     1          # Minimum nonlinear iterations
DECR_FACTOR         1.2        # Step decrease factor on failure
INCR_FACTOR         1.2        # Step increase factor on success
MIN_MAXSTEP         1.0        # Minimum allowed max step size
```

**Key tradeoffs:**
- ABSTOL: tighter = better mass conservation but slower. Default 1e-4 is safe.
- MAX_SOLVER_STEP: larger = faster but may miss rapid events.

#### Output Control
```
# Interval codes: -1=yearly, -2=monthly, -3=daily, -4=hourly, 0=off, N=every N seconds
SURF          -3       # Surface water depth (daily)
UNSAT         -3       # Unsaturated zone (daily)
GW            -3       # Groundwater (daily)
RIVSTG        -3       # River stage (daily)
SNOW          -3       # Snow water equivalent (daily)
CMC           0        # Canopy moisture (off)
INFIL         -3       # Infiltration (daily)
RECHARGE      -3       # Recharge (daily)
EC            -3       # Canopy evaporation (daily)
ETT           -3       # Transpiration (daily)
EDIR          -3       # Direct evaporation (daily)
RIVFLX0       0        # Upstream flux (off)
RIVFLX1       -3       # Downstream flux (daily)
RIVFLX2       0        # Left bank surface (off)
RIVFLX3       0        # Right bank surface (off)
RIVFLX4       0        # Left bank aquifer (off)
RIVFLX5       0        # Right bank aquifer (off)
SUBFLX        0        # Subsurface flux (off)
SURFFLX       0        # Surface flux (off)
IC            -2       # Initial conditions (monthly)
```

**WARNING (dt_014):** Setting a variable to `3` means every 3 SECONDS, not daily!
Use `-3` for daily output.

### Step 2: Configure .calib File

All values are **multipliers** (default = 1.0), except SFCTMP which is an
**additive offset** in Kelvin.

```
# Soil hydraulic multipliers
KSATH         1.0      # Horizontal Ksat multiplier
KSATV         1.0      # Vertical Ksat multiplier
KINF          1.0      # Infiltration Ksat multiplier
KMACSATH      1.0      # Horizontal macropore Ksat multiplier
KMACSATV      1.0      # Vertical macropore Ksat multiplier

# Soil property multipliers
POROSITY      1.0      # Porosity multiplier
ALPHA         1.0      # van Genuchten alpha multiplier
BETA          1.0      # van Genuchten n multiplier
MACVF         1.0      # Vertical macropore fraction multiplier
MACHF         1.0      # Horizontal macropore fraction multiplier
DMAC          1.0      # Macropore depth multiplier

# Vegetation multipliers
VEGFRAC       1.0      # Vegetation fraction multiplier
ALBEDO        1.0      # Albedo multiplier
ROUGH         1.0      # Surface roughness multiplier
DROOT         1.0      # Rooting depth multiplier

# River multipliers
ROUGH_RIV     1.0      # River roughness multiplier
KRIVH         1.0      # River bed Ksat multiplier
RIV_DPTH      1.0      # River depth multiplier
RIV_WDTH      1.0      # River width multiplier

# Forcing adjustments
PRCP          1.0      # Precipitation multiplier (1.0 = no change)
SFCTMP        0.0      # Temperature offset in K (0.0 = no change)
```

**WARNING (dt_011):** These are MULTIPLIERS. `KSATH=1e-5` means multiply base Ksat
by 0.00001, effectively shutting off lateral flow. Use values near 1.0 for initial runs.

### Step 3: Verify Configuration

1. Check that START/END covers your forcing data period
2. Ensure ABSTOL is 1e-4 or tighter
3. All .calib multipliers near 1.0 for first run
4. Output intervals use correct codes (-3 for daily, not 3)
5. Output variables cover all needed diagnostics

## Verification

- Parse .para and .calib files to check for out-of-range values
- Run a short test (1 month) before committing to full simulation
- Check output file sizes are reasonable (not GB for a small catchment)

## Traps

| Trap | Triplet | Severity |
|------|---------|----------|
| Calibration multiplier vs absolute value | dt_011 | Silent |
| Output interval code confusion | dt_014 | Degraded |
| CVODE tolerance too loose | dt_013 | Degraded |

## Example

Shale Hills configuration for a 1-year simulation:

```
# .para settings
SIMULATION_MODE    0
INIT_MODE          1        # Using spin-up IC
START              2009-01-01 00:00
END                2009-12-31 23:00
MODEL_STEPSIZE     60
ABSTOL             1.0E-04
GW                 -3       # Daily groundwater output
RIVFLX1            -4       # Hourly downstream river flux
```
