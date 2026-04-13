# Stage 4: Simulation Execution

## Purpose

Run the DualSPHysics solver on the generated case. The solver reads the initial particle distribution (bi4) and time-steps the SPH equations, outputting particle data at specified intervals. This is the computationally expensive stage.

## Inputs

| Input | Format | Source |
|-------|--------|--------|
| `Case.bi4` | Binary | Stage 2 (GenCase) output |
| CLI options | Command-line | User/script |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `Part_XXXX.bi4` | Binary | Particle data per output timestep |
| `Part_XXXX.ibi4` | Text | Output metadata |
| `PartOut_XXXX.bi4` | Binary | Excluded particles |
| `RUN.out` | Text | Simulation log |
| `RUN.csv` | CSV | Summary statistics |

## Procedure

1. **Set LD_LIBRARY_PATH** for shared libraries:
   ```bash
   export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/path/to/bin/linux
   ```

2. **Run CPU version** (no GPU needed):
   ```bash
   DualSPHysics5.4CPU_linux64 output/CaseName output/ -cpu
   ```

3. **Run GPU version** (CUDA required):
   ```bash
   DualSPHysics5.4_linux64 output/CaseName output/ -gpu:0
   ```

4. **Monitor progress**: Check stdout for PART output lines showing time, dt, particle count

5. **Override parameters from CLI** (optional):
   ```bash
   DualSPHysics5.4CPU_linux64 case output/ -cpu -tmax:5.0 -tout:0.05 -sv:binx
   ```

## Verification

- [ ] Solver starts without errors
- [ ] First few timesteps complete (dt is reasonable)
- [ ] Particle count remains stable (not losing many particles)
- [ ] Part_*.bi4 files appear in data/ directory
- [ ] Simulation reaches TimeMax
- [ ] Return code is 0
- [ ] RUN.out contains completion message

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Missing LD_LIBRARY_PATH | libChronoEngine.so not found | Export LD_LIBRARY_PATH |
| CUDA not installed | "CUDA error" on GPU mode | Use -cpu flag |
| dp too small | Runs for hours/days | Increase dp, decrease domain |
| CFL too large | Simulation blows up (NaN) | Reduce CFL to 0.1-0.2 |
| No DDT | Noisy pressure field | Enable -ddt:2 |
| RhopOut too tight | Many particles excluded | Widen RhopOutMin/Max range |
| Not enough memory | Segfault or OOM | Increase dp or reduce domain |
| Binary not executable | Permission denied | chmod +x binary |

## Runtime Estimation

| Particles | CPU time (per sec sim) | GPU time (per sec sim) |
|-----------|----------------------|----------------------|
| 10,000 | ~10 seconds | ~1 second |
| 100,000 | ~2 minutes | ~10 seconds |
| 1,000,000 | ~30 minutes | ~2 minutes |
| 10,000,000 | ~5 hours | ~20 minutes |

*Approximate values. Depends on hardware, kernel, features enabled.*

## Common CLI Patterns

```bash
# Quick test (10 steps only)
DualSPHysics5.4CPU_linux64 case output/ -cpu -nsteps:10

# Debug with VTK output
DualSPHysics5.4CPU_linux64 case output/ -cpu -sv:binx,vtk -nsteps:100

# Production run with DDT and mDBC
DualSPHysics5.4CPU_linux64 case output/ -cpu -mdbc -ddt:2 -symplectic

# GPU with specific device
DualSPHysics5.4_linux64 case output/ -gpu:1 -sv:binx

# Stable/reproducible
DualSPHysics5.4CPU_linux64 case output/ -cpu -stable
```

## Example

```bash
export dirbin=bin/linux
export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:${dirbin}

# Run dam break simulation (CPU)
${dirbin}/DualSPHysics5.4CPU_linux64 output/CaseDambreak output/ -cpu

# Expected output pattern:
# Part_0000  Time:0.0000  dt:3.3e-05  Parts:245832  ...
# Part_0001  Time:0.0100  dt:3.3e-05  Parts:245832  ...
# ...
# Part_0160  Time:1.6000  dt:2.8e-05  Parts:245102  ...
# Finished (code=0).
```
