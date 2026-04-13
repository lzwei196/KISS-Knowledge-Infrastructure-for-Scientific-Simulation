# S4: Model Assembly — Combining Packages into a MODFLOW Simulation

## Purpose

Assemble all prepared data (grid, properties, forcing, boundaries) into a complete MODFLOW simulation using FloPy's Python API. Write all input files to disk for MODFLOW execution.

## Inputs

| Input | From Stage | FloPy Object |
|-------|-----------|--------------|
| Grid arrays (top, botm, delr, delc) | S1 | DIS / ModflowGwfdis |
| Aquifer properties (K, Ss, Sy) | S2 | NPF + STO / ModflowLpf |
| Recharge arrays | S3 | RCH / ModflowGwfrcha |
| Well data | S3 | WEL / ModflowGwfwel |
| River data | S3 | RIV / ModflowGwfriv |
| Initial heads | User/S1 | IC / ModflowGwfic |

## Outputs

| Output | Description |
|--------|-------------|
| `mfsim.nam` | Simulation name file (MF6 master control) |
| `model.nam` | Model name file (lists all packages) |
| `model.dis` | Discretization file |
| `model.npf` | Node property flow file |
| `model.ic` | Initial conditions |
| `model.oc` | Output control |
| All package files | .rch, .wel, .riv, .chd, .sto, etc. |

## Procedure — MODFLOW 6

### Step 1: Create Simulation

```python
import flopy
import numpy as np

ws = './model_workspace'
name = 'mymodel'

# Simulation container
sim = flopy.mf6.MFSimulation(
    sim_name=name,
    sim_ws=ws,
    exe_name='mf6'         # Must be on PATH or full path
)
```

### Step 2: Temporal Discretization

```python
# Define stress periods: (length_days, n_timesteps, multiplier)
tdis = flopy.mf6.ModflowTdis(
    sim,
    nper=12,                 # 12 monthly stress periods
    perioddata=[
        (31, 1, 1.0),       # January: 31 days, 1 step
        (28, 1, 1.0),       # February
        # ... etc
    ]
)
```

### Step 3: Solver

```python
ims = flopy.mf6.ModflowIms(
    sim,
    complexity='MODERATE',   # SIMPLE, MODERATE, or COMPLEX
    outer_maximum=100,       # Max outer iterations (increase if non-convergence)
    inner_maximum=50,        # Max inner iterations
    outer_dvclose=1e-4,      # Head change criterion (m)
    inner_dvclose=1e-5,      # Head change criterion inner
)
```

### Step 4: Groundwater Flow Model

```python
gwf = flopy.mf6.ModflowGwf(
    sim,
    modelname=name,
    save_flows=True          # Required for budget output
)
```

### Step 5: Add Packages

```python
# Discretization
dis = flopy.mf6.ModflowGwfdis(gwf, nlay=nlay, nrow=nrow, ncol=ncol,
                                delr=delr, delc=delc, top=top, botm=botm)

# Initial conditions (starting heads)
ic = flopy.mf6.ModflowGwfic(gwf, strt=top)  # Start at land surface

# Aquifer properties
npf = flopy.mf6.ModflowGwfnpf(gwf, k=hk, save_specific_discharge=True)

# Storage (for transient models)
sto = flopy.mf6.ModflowGwfsto(gwf, ss=ss, sy=sy,
                                steady_state={0: True},
                                transient={1: True})

# Output control
oc = flopy.mf6.ModflowGwfoc(gwf,
    head_filerecord=f'{name}.hds',
    budget_filerecord=f'{name}.bud',
    saverecord=[('HEAD', 'ALL'), ('BUDGET', 'ALL')])
```

### Step 6: Write Files

```python
sim.write_simulation()
# This creates all files in ws/
```

## Verification

- [ ] All package files written to workspace (check with `os.listdir(ws)`)
- [ ] `mfsim.nam` references all model files
- [ ] `model.nam` lists all packages
- [ ] Initial heads are above layer bottoms (prevents initial dry cells)
- [ ] Stress period lengths sum to desired simulation duration
- [ ] save_flows=True if budget output needed
- [ ] Output control saves HEAD and BUDGET for desired time steps

## Traps

| ID | Trap | Symptom | Fix |
|----|------|---------|-----|
| dt_011 | Mixing MF6 and MF2005 API | AttributeError or wrong file format | Use `flopy.mf6.*` for MF6, `flopy.modflow.*` for MF2005 |
| dt_014 | Missing LAYERED keyword | All layers get same properties | Use `LAYERED` for per-layer arrays in MF6 |
| dt_015 | Steady-state flag wrong | Storage terms ignored in transient periods | Set `transient={period: True}` for transient periods |
| dt_009 | Off-by-one in boundary cells | Boundaries in wrong locations | FloPy is zero-based, not 1-based |
| — | Missing save_flows | No budget output file | Set `save_flows=True` on GWF model |
| — | exe_name not found | FileNotFoundError at runtime | Run `get-modflow :` or set full path |

## Example — Complete Assembly Script

```python
import flopy
import numpy as np

ws, name = './bengbu_gw', 'bengbu'
sim = flopy.mf6.MFSimulation(sim_name=name, sim_ws=ws, exe_name='mf6')
tdis = flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(365, 12, 1.2)])
ims = flopy.mf6.ModflowIms(sim, complexity='MODERATE')
gwf = flopy.mf6.ModflowGwf(sim, modelname=name, save_flows=True)

# Load prepared arrays
top = np.load('grid_output/top.npy')
botm = np.load('grid_output/botm.npy')
hk = np.load('aquifer_props/hk.npy')

dis = flopy.mf6.ModflowGwfdis(gwf, nlay=3, nrow=40, ncol=20,
                                delr=250, delc=250, top=top, botm=botm)
ic = flopy.mf6.ModflowGwfic(gwf, strt=top - 5)
npf = flopy.mf6.ModflowGwfnpf(gwf, k=hk, save_specific_discharge=True)
rcha = flopy.mf6.ModflowGwfrcha(gwf, recharge=0.0003)  # 0.3 mm/day
oc = flopy.mf6.ModflowGwfoc(gwf,
    head_filerecord=f'{name}.hds', budget_filerecord=f'{name}.bud',
    saverecord=[('HEAD', 'ALL'), ('BUDGET', 'ALL')])

sim.write_simulation()
print(f"Model files written to {ws}/")
```
