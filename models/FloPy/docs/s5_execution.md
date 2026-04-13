# S5: Execution — Running MODFLOW and Handling Convergence

## Purpose

Execute the MODFLOW binary, monitor convergence, and handle common runtime errors. This stage wraps the call to `mf6`, `mf2005`, or other MODFLOW executables with pre-flight checks and post-run validation.

## Inputs

| Input | Description |
|-------|-------------|
| Model workspace | Directory with all MODFLOW input files |
| MODFLOW binary | `mf6`, `mf2005`, `mfnwt`, etc. |
| Timeout setting | Maximum runtime in seconds |

## Outputs

| Output | Description |
|--------|-------------|
| `.hds` | Binary head file |
| `.bud` / `.cbc` | Binary cell-by-cell budget file |
| `.lst` | Listing file (text log + water balance) |
| Return code | 0 = success, non-zero = failure |

## Procedure

### Running with FloPy

```python
# Method 1: FloPy simulation run (recommended for MF6)
success, buff = sim.run_simulation()
if not success:
    print("MODFLOW failed!")
    # Check buff for error messages

# Method 2: FloPy model run (MF2005)
success, buff = model.run_model()

# Method 3: Direct subprocess (any version)
import subprocess
result = subprocess.run(['mf6'], cwd='./model_workspace',
                       capture_output=True, text=True, timeout=600)
```

### Running with the KI Tool

```bash
python tools/run_modflow.py --workspace ./model_workspace --version mf6 --timeout 300
```

## Convergence Troubleshooting

### Non-Convergence (dt_016)

**Symptom**: "FAILED TO CONVERGE" in listing file or stdout.

**Causes and fixes**:

| Cause | Fix |
|-------|-----|
| Too few iterations | Increase `outer_maximum` (100→500) and `inner_maximum` (50→200) |
| Closure criterion too tight | Relax `outer_dvclose` (1e-6→1e-4) |
| Poor initial heads | Set starting heads closer to expected solution |
| Unrealistic parameters | Check K, recharge, boundary conditions for unit errors |
| Dry cells oscillating | Switch to Newton-Raphson solver (MF6: `COMPLEXITY COMPLEX`) |

### Solver Settings

```python
# Conservative settings for difficult models
ims = flopy.mf6.ModflowIms(
    sim,
    complexity='COMPLEX',        # Enables Newton-Raphson
    outer_maximum=500,
    inner_maximum=200,
    outer_dvclose=1e-3,          # Relaxed outer criterion
    inner_dvclose=1e-4,
    linear_acceleration='BICGSTAB',
    under_relaxation='DBD',
    under_relaxation_gamma=0.0,
    under_relaxation_theta=0.85,
)
```

### Oscillating Heads (dt_017)

**Symptom**: Heads bounce between two values across iterations.

**Fix**: Enable under-relaxation or switch to Newton solver. For MF2005, use MODFLOW-NWT.

### Extremely Slow Convergence (dt_018)

**Symptom**: Model runs for hours on a simple problem.

**Causes**:
- Extremely small cells next to large cells (aspect ratio > 10)
- Very high K contrast between adjacent cells (>1000x)
- Solver preconditioner not matching problem structure

**Fix**: Improve grid quality, smooth K transitions, try different linear_acceleration.

## Verification

- [ ] Return code = 0
- [ ] No "FAILED TO CONVERGE" in output
- [ ] Water balance percent discrepancy < 1%
- [ ] .hds and .bud files created and non-empty
- [ ] Runtime is reasonable for model size
- [ ] No "ERROR" messages in listing file

## Expected Runtimes

| Model Size | Steady-State | Transient (100 periods) |
|-----------|-------------|------------------------|
| 1,000 cells | < 1 sec | 1-5 sec |
| 10,000 cells | 1-5 sec | 10-60 sec |
| 100,000 cells | 5-30 sec | 1-10 min |
| 1,000,000 cells | 1-10 min | 10-60 min |

## Traps

| ID | Trap | Symptom | Fix |
|----|------|---------|-----|
| dt_016 | Non-convergence | "FAILED TO CONVERGE" | Increase iterations, relax criteria |
| dt_017 | Oscillating heads | Heads alternate between values | Under-relaxation or Newton solver |
| dt_018 | Slow convergence | Hours for simple model | Check grid quality, K contrasts |
| — | Binary not found | FileNotFoundError | Run `get-modflow :` to install |
| — | Permission denied | OSError | `chmod +x path/to/mf6` |

## Example

```bash
# Run with 5-minute timeout
python tools/run_modflow.py \
    --workspace ./model_workspace \
    --version mf6 \
    --timeout 300

# Check output
python -c "
import flopy
hds = flopy.utils.HeadFile('./model_workspace/mymodel.hds')
print(f'Times: {hds.get_times()}')
print(f'Shape: {hds.get_data().shape}')
"
```
