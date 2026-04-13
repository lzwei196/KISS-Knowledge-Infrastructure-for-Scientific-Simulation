# Skill: Model Execution

## Purpose

Execute a MARRMoT model simulation using prepared forcing data and parameters.
This skill covers both direct MATLAB/Octave execution and the Python wrapper
approach via `run_marrmot.py`.

The execution stage takes the forcing array [P, Ep, T], parameter vector
(theta), initial storages (S0), and solver settings, runs the model for all
timesteps, and produces flux outputs, storage trajectories, and a water
balance check.

## Inputs

| Input                  | Source                      | Format          | Unit        |
|------------------------|-----------------------------|-----------------|-------------|
| Forcing CSV            | `convert_forcing.py`        | CSV             | mm/d, deg C |
| Parameter JSON         | `convert_parameters.py`     | JSON            | mixed       |
| Model name             | User selection              | String          | -           |
| delta_t                | Forcing time step           | Scalar          | days        |
| Solver tolerance       | User / default              | Scalar          | mm          |
| Solver max iterations  | User / default              | Integer         | -           |

## Outputs

| Output                      | Format   | Contents                              |
|-----------------------------|----------|---------------------------------------|
| `marrmot_timeseries.csv`    | CSV      | timestep, Q_mm_d, Ea_mm_d             |
| `run_output.json`           | JSON     | Status, metrics, paths, warnings       |
| Console output              | Text     | Water balance summary                  |

### MARRMoT native outputs (from `get_output()`):

1. **fluxOutput**: [n_timesteps x n_outfluxes] array
   - Column 1: Total streamflow Q (mm/d)
   - Column 2+: Other outgoing fluxes (model-dependent)

2. **fluxInternal**: Struct with named fields for every internal flux
   - e.g., `ea` (actual evaporation), `qf` (fast flow), `qs` (slow flow)

3. **storeInternal**: Struct with named fields for every store
   - e.g., `S1` (soil moisture), `S2` (fast reservoir)

4. **waterBalance**: Scalar — should be near zero if mass is conserved

## Procedure

### Using Python wrapper:

1. **Prepare inputs**: Ensure forcing.csv and params.json are ready.

2. **Run wrapper**:
   ```bash
   python tools/run_marrmot.py \
     --forcing forcing.csv \
     --model m_29_hymod_5p_5s \
     --params params.json \
     --output run_output.json
   ```

3. **Wrapper internally**:
   a. Generates temporary Octave .m script
   b. Script loads forcing CSV, creates model object, sets properties
   c. Calls `m.get_output()` which runs the implicit Euler solver
   d. Writes Q and Ea timeseries to CSV
   e. Prints summary JSON between SUMMARY_JSON_START/END markers

4. **Check return code**: Non-zero means Octave error. Check stderr.

### Using MATLAB/Octave directly:

```matlab
% Load forcing
data = readmatrix('forcing.csv', 'NumHeaderLines', 5);
P = data(:,2); Ep = data(:,3); T = data(:,4);

% Create and configure model
m = feval('m_29_hymod_5p_5s');
m.theta = [200, 1.5, 0.7, 0.15, 0.01];
m.input_climate = [P, Ep, T];   % CRITICAL: [P, Ep, T] order
m.delta_t = 1;                   % CRITICAL: must match forcing
m.S0 = [0, 0, 0, 0, 0];         % CRITICAL: length == numStores

% Optional: adjust solver
m.solver_opts.resnorm_tolerance = 0.1;
m.solver_opts.resnorm_maxiter = 6;

% Run
[fluxOut, fluxInt, storeInt, wb] = m.get_output();
Q = fluxOut(:,1);  % streamflow mm/d
```

### Solver behaviour:

The solver uses a cascade fallback strategy:
1. **NewtonRaphson** (custom, fastest)
2. **fsolve** (MATLAB/Octave built-in, if tolerance not met)
3. **lsqnonlin** (bounded, last resort)

If all fail within one iteration, up to `resnorm_maxiter` re-runs with
different starting points (previous solution, store boundaries, random).

## Verification

| Check                        | Expected                | Action if fails    |
|------------------------------|-------------------------|--------------------|
| Octave exit code             | 0                       | Read stderr         |
| Water balance                | < 1 mm over full period | Increase maxiter    |
| Q values                     | >= 0                    | Check parameters    |
| Q mean                       | 0.1 - 50 mm/d          | Check forcing units |
| No solver warnings           | No fallback messages    | Increase tolerance  |

## Traps

- **dt_009**: `delta_t = 24` when forcing is daily. This makes the model
  think each timestep is 24 days, inflating all fluxes by 24x. Always
  use `delta_t = 1` for daily data.

- **dt_011**: Climate array columns in wrong order `[P, T, Ep]` instead
  of `[P, Ep, T]`. Model treats temperature as PET and vice versa.
  Produces unrealistic evaporation and nonsensical Q.

- **dt_012**: S0 vector length mismatch. For m_29_hymod with 5 stores,
  `S0 = [0, 0]` causes "Index exceeds array dimensions" error.
  Always check `m.numStores` first.

- **dt_013**: Solver convergence issues on stiff problems (very large Smax
  with near-empty initial storage, or extreme parameter values near
  boundaries). Increase `resnorm_maxiter` to 12 or more. Check the 5th
  output argument `solverSteps` for diagnostics.

- **dt_014**: Water balance error is printed to console but does not stop
  execution. A balance > 1 mm over the simulation period indicates
  numerical issues. Always check this value.

## Example

```bash
python tools/run_marrmot.py \
  --forcing forcing.csv \
  --model m_29_hymod_5p_5s \
  --params params.json \
  --delta-t 1.0 \
  --solver-tol 0.1 \
  --solver-maxiter 6 \
  --output run_output.json \
  --timeout 300
```

Expected console output:
```
Loaded 3652 timesteps of forcing data
P mean: 3.45 mm/d, Ep mean: 2.10 mm/d, T mean: 12.5 C
Model: m_29_hymod_5p_5s (5 params, 5 stores)
Running model...
Model run complete.
Water balance: 0.0023 mm
Output written to marrmot_timeseries.csv
```
