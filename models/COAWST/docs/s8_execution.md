# S8: Model Execution

## Purpose
Run the compiled COAWST binary (coawstM for coupled, romsM for standalone ROMS) with validated configuration files and monitor for runtime failures.

## Inputs
| Input                 | Format     | Source               | Required |
|-----------------------|------------|----------------------|----------|
| COAWST binary         | Executable | Stage s7 (build)     | Yes      |
| ocean.in              | Text       | Stage s6             | Yes      |
| coupling.in           | Text       | Stage s5 (coupled)   | Coupled  |
| Grid file             | NetCDF     | Stage s1             | Yes      |
| Initial conditions    | NetCDF     | Stage s3             | Yes      |
| Forcing files         | NetCDF     | Stage s2             | Yes      |
| Boundary conditions   | NetCDF     | Stage s4             | Open BC  |
| SCRIP weights         | NetCDF     | Stage s5 (coupled)   | Coupled  |
| SWAN input            | Text       | Stage s5 (coupled)   | Waves    |

## Outputs
| Output              | Format  | Contents                                         |
|---------------------|---------|--------------------------------------------------|
| History files       | NetCDF  | Full 3D state snapshots (every NHIS timesteps)   |
| Average files       | NetCDF  | Time-averaged fields (every NAVG timesteps)      |
| Restart files       | NetCDF  | Checkpoint for continuation runs                 |
| Station files       | NetCDF  | Time series at specified locations                |
| Standard output     | Text    | Runtime log, timing, diagnostics                 |

## Procedure

1. **Preflight check** (automated by `run_coawst.py`):
   - Binary exists and is executable
   - All referenced input files exist
   - NtileI × NtileJ matches allocated ocean processors
   - Sufficient disk space

2. **Execute**:
   ```bash
   # Coupled run
   python3 ki/tools/run_coawst.py \
     --binary ./coawstM \
     --config coupling_sandy.in \
     --nprocs 16 --timeout 7200

   # Or directly:
   mpirun -np 16 ./coawstM coupling_sandy.in

   # Standalone ROMS
   mpirun -np 4 ./romsM ocean_upwelling.in
   ```

3. **Monitor output**: Watch for:
   - `BLOWUP` message → CFL violation, reduce DT or increase NDTFAST
   - `NaN` in fields → forcing data gap or boundary condition issue
   - Model reaching `NTIMES` → successful completion
   - `Elapsed wall time` → timing information

4. **Verify outputs**:
   ```bash
   ncdump -h sandy_his.nc | head -30
   # Check that time dimension has expected number of records
   ```

## Verification

### Success Indicators
- Model prints timing summary at end
- History file contains expected number of time records: `NTIMES / NHIS`
- No NaN values in output fields
- Restart file is written (for continuation runs)

### Failure Diagnosis
| Symptom                        | Likely Cause               | Fix                               | Triplet |
|-------------------------------|-----------------------------|------------------------------------|---------|
| Immediate crash, segfault      | Wrong NtileI×NtileJ       | Match to mpirun -np N              | dt_004  |
| BLOWUP after few steps         | DT too large for grid      | Reduce DT or increase NDTFAST      | dt_005  |
| NaN appears, then BLOWUP       | Forcing data gap           | Check time coverage of forcing     | dt_003  |
| Runs but SST ~300°C            | Temperature in K not °C    | Fix forcing unit conversion        | dt_001  |
| Runs but currents 1000× strong | Stress in Pa not m²/s²     | Divide by rho0 (1025)              | dt_002  |
| Hangs indefinitely             | MPI deadlock (proc mismatch)| Check coupling.in proc allocation | dt_004  |
| Model runs but no output files | NHIS=0 or very large NHIS  | Set NHIS to reasonable value       | —       |
| Restart fails                  | Time mismatch in rst file  | Check NRREC and time reference     | dt_013  |

## Traps

**dt_005: CFL blowup.**
The Courant-Friedrichs-Lewy condition requires `c × dt / dx < 1` where c is the fastest wave speed (barotropic: √(g·h)). With `DT=300s`, `NDTFAST=20`, the barotropic timestep is 15s. For h=5000m and dx=1km: CFL = √(9.81×5000) × 15 / 1000 = 3.3 → **BLOWUP**. Fix: reduce DT or increase NDTFAST.

**dt_013: Restart time mismatch.**
When restarting from a checkpoint, `NRREC` in ocean.in must match the time record in the restart file. If NRREC=0, ROMS uses the latest record. If you provide NRREC=1 but the restart file has records at different times, the simulation clock will be wrong and forcing interpolation will fail.

**Output file size.**
A 500×500×30 grid writing history every 100 steps for 10000 steps creates ~100 3D snapshots. At 4 bytes × 500 × 500 × 30 × 5 variables × 100 records ≈ 15 GB. Plan disk space accordingly.

## Example

```bash
# Full Sandy coupled run
cd Projects/Sandy
mpirun -np 16 ../../coawstM coupling_sandy.in > sandy_log.txt 2>&1 &

# Monitor progress
tail -f sandy_log.txt | grep -E "time|BLOWUP|NaN|DEF_HIS"

# After completion, check output
ncdump -v ocean_time sandy_his.nc | tail -5
python3 ../../ki/tools/parse_output.py \
  --history sandy_his.nc --variable zeta --level surface \
  --lon -74.0 --lat 39.5 --output zeta_timeseries.csv
```
