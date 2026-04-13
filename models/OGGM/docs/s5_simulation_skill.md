# Stage 5: Glacier Dynamics Simulation

## Purpose

Run the glacier dynamics simulation to compute glacier evolution (volume, area, length changes) and hydrological outputs (melt, precipitation, refreezing, runoff) over historical and future periods. This stage integrates the calibrated mass balance with ice flow dynamics to produce physically consistent glacier trajectories. The hydrological output from this stage is the key input for VIC coupling in Stage 6.

## Prerequisites

- **Mass balance calibrated** (Stage 4 complete — all GDirs have calibrated mu_star, pcf, tbias)
- **For projections**: CMIP6 climate data processed (from Stage 3)
- **Sufficient disk space**: Output files are ~1-5 MB per glacier per simulation

## Inputs

### Historical Simulation

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| `working_dir` | directory | Yes | OGGM working directory |
| `start_year` | int | Yes | Simulation start year |
| `end_year` | int | Yes | Simulation end year |
| `use_spinup` | bool | No | Dynamic spinup (default true) |
| `model_type` | string | No | 'FluxBased' (default) or 'SemiImplicit' |
| `output_suffix` | string | No | File suffix for output naming |

### Projection Simulation

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| `working_dir` | directory | Yes | OGGM working directory |
| `gcm` | string | Yes | GCM name |
| `ssp` | string | Yes | SSP scenario |
| `start_year` | int | Yes | Projection start year |
| `end_year` | int | Yes | Projection end year |

## Procedure

### Step 1: Choose Flowline Model

OGGM provides two flowline dynamics solvers:

**FluxBasedModel (default):**
- Explicit forward Euler scheme
- Timestep limited by CFL condition: dt < dx / max_velocity
- Faster for most glaciers (typical timestep: hours to days)
- Can become numerically unstable for very steep or thin glaciers
- If unstable, raises RuntimeError or produces NaN values

**SemiImplicitModel:**
- Implicit trapezoidal scheme
- Unconditionally stable — no CFL restriction
- Slightly slower per timestep but can use larger timesteps
- Recommended for: very steep glaciers, extremely long simulations (>500 years), or if FluxBased fails

**Decision**: Start with FluxBased. Switch to SemiImplicit only if FluxBased fails with numerical instability (dt_014).

### Step 2: Dynamic Spinup

The RGI inventory provides glacier outlines at a specific date (typically ~2003 for RGI v6). To start a simulation before this date, OGGM needs to "spin up" — find the glacier state at an earlier date that, when evolved forward, matches the RGI inventory date.

Dynamic spinup procedure:
1. Start from a larger initial glacier (e.g., 1.1x current area)
2. Run forward to the RGI date
3. Compare result with RGI area/volume
4. Iterate until the simulated glacier at the RGI date matches observations

```python
workflow.execute_entity_task(
    tasks.run_with_hydro, gdirs,
    run_task=tasks.run_dynamic_spinup,
    min_ys=1979,
    store_monthly_hydro=True
)
```

If spinup doesn't converge (dt_015), the glacier may have complex dynamics (surging, calving) that prevent a smooth back-calculation. In such cases, start the simulation from the RGI date instead.

### Step 3: Run Historical Simulation

```python
from oggm import tasks, workflow

workflow.execute_entity_task(
    tasks.run_with_hydro, gdirs,
    run_task=tasks.run_from_climate_data,
    min_ys=start_year,
    max_ys=end_year,
    store_monthly_hydro=True,  # CRITICAL for VIC coupling
    output_filesuffix='_historical'
)
```

**`store_monthly_hydro=True` is essential** for VIC coupling. Without it, only annual glacier diagnostics are saved, and monthly melt runoff for Stage 6 is unavailable.

### Step 4: Run Future Projections

```python
for ssp in ['ssp126', 'ssp245', 'ssp585']:
    rid = f'{gcm}_{ssp}'
    workflow.execute_entity_task(
        tasks.run_with_hydro, gdirs,
        run_task=tasks.run_from_climate_data,
        climate_filename='gcm_data',
        climate_input_filesuffix=f'_{rid}',
        min_ys=2020, max_ys=2100,
        store_monthly_hydro=True,
        output_filesuffix=f'_{rid}'
    )
```

The projection starts from the end state of the historical run (or spinup). Each GCM/SSP combination produces a separate output file.

### Step 5: Compile Output

```python
from oggm import utils

# Compile per-glacier output into basin-level dataset
ds = utils.compile_run_output(gdirs, input_filesuffix='_historical')

# Compile glacier statistics
df_stats = utils.compile_glacier_statistics(gdirs)
```

The compiled dataset contains:
- `volume` — Total glacier volume (m3) per year
- `area` — Total glacier area (m2) per year
- `length` — Glacier length (m) per year

The monthly hydro output (melt, runoff) is in `run_output_hydro_{suffix}.nc` per GDir and must be compiled separately.

### Step 6: Output Variables

**model_diagnostics.nc** (annual):
| Variable | Unit | Description |
|----------|------|-------------|
| `volume_m3` | m3 | Total ice volume |
| `area_m2` | m2 | Glacier area |
| `length_m` | m | Glacier length (main flowline) |
| `calving_m3` | m3 | Calving flux (tidewater glaciers) |

**run_output_hydro.nc** (monthly, if store_monthly_hydro=True):
| Variable | Unit | Description |
|----------|------|-------------|
| `melt_off_glacier` | kg/m2/month | Off-glacier snowmelt |
| `melt_on_glacier` | kg/m2/month | On-glacier melt (ice + snow) |
| `liq_prcp_off_glacier` | kg/m2/month | Liquid precipitation off-glacier |
| `liq_prcp_on_glacier` | kg/m2/month | Liquid precipitation on-glacier |
| `snowfall_off_glacier` | kg/m2/month | Snowfall off-glacier |
| `snowfall_on_glacier` | kg/m2/month | Snowfall on-glacier |
| `refreezing` | kg/m2/month | Refreezing of meltwater |

**For VIC coupling, the key variable is `melt_on_glacier`** — this is the glacier ice and snow melt that produces runoff. `melt_off_glacier` is handled by VIC.

## Expected Outputs

| Output | Location | Description |
|--------|----------|-------------|
| `model_diagnostics{suffix}.nc` | Per GDir | Annual volume, area, length |
| `run_output_hydro{suffix}.nc` | Per GDir | Monthly hydrological components |
| Compiled output | `{output_dir}/compiled_output{suffix}.nc` | Basin-aggregate time series |
| Glacier statistics | `{output_dir}/glacier_statistics.csv` | Per-glacier summary |

## Validation Checks

1. **No NaN values** in output time series — indicates numerical instability
2. **Volume >= 0** at all timesteps — negative volume is physically impossible
3. **Area monotonically decreases** under sustained negative mass balance (not strictly required but expected for warming scenarios)
4. **Conservation** — mass balance should be consistent with volume change (dV/dt = integral of MB over area)
5. **Reasonable magnitudes** — typical glacier velocities < 1000 m/yr for most glaciers
6. **Output time range** — covers requested start_year to end_year

## Common Pitfalls

### FluxBasedModel Extremely Slow (dt_014)
The FluxBased model uses a CFL-limited timestep. For very steep glacier tongues or very thin ice, the CFL condition requires extremely small timesteps (seconds), making simulation impractically slow. Solution: switch to SemiImplicitModel.

### Dynamic Spinup Doesn't Converge (dt_015)
If the spinup iteration doesn't converge to the observed RGI area within ~20 iterations, the glacier may have: (a) surging behavior, (b) calving that changes area non-monotonically, (c) DEM or outline errors. Solution: skip spinup and start from the RGI date.

### Memory Error with Many Glaciers (dt_020)
Processing >500 glaciers simultaneously with `store_monthly_hydro=True` can exhaust memory because monthly output for each glacier is held in RAM during compilation. Solution: process in batches of 100-500, or compile output incrementally.

### Hydrological Year vs Calendar Year (dt_016)
OGGM's monthly hydro output uses hydrological year (Oct-Sep in NH). Month index 1 = October, not January. When extracting monthly data for VIC coupling, always use the actual dates from the time coordinate, not month indices.

### Missing store_monthly_hydro
Forgetting `store_monthly_hydro=True` in `run_with_hydro` means only annual diagnostics are saved. Monthly melt, precipitation, and runoff — needed for VIC coupling — will be unavailable. You must re-run the simulation with this flag.

### Projection Starting State
Projections should start from the end state of the historical run, not from the RGI date. If the historical run ends in 2020 and the projection starts in 2020, the transition is seamless. If there is a gap (historical ends 2018, projection starts 2020), fill with a short historical extension.

## Tools Reference

| Tool | Script | Purpose |
|------|--------|---------|
| `run_glacier_simulation` | `tools/s5_simulation/run_glacier_simulation.py` | Historical dynamics |
| `run_glacier_projections` | `tools/s5_simulation/run_glacier_projections.py` | Future scenarios |
| `compile_glacier_output` | `tools/s5_simulation/compile_glacier_output.py` | Aggregate output |
