# Stage 4: Model Configuration and Execution

## Purpose

Configure MOM6 runtime parameters, write the namelist and diagnostic table, and
execute the model binary. This stage covers the final assembly of all configuration
files and the actual simulation run.

## Inputs

| File              | Format          | Description                            |
|-------------------|-----------------|----------------------------------------|
| `MOM_input`       | Key-value text  | Physics and numerics parameters        |
| `MOM_override`    | Key-value text  | Parameter overrides (optional)         |
| `input.nml`       | Fortran namelist| Run control (dates, I/O, FMS settings) |
| `diag_table`      | Custom text     | Diagnostic output configuration        |
| `INPUT/` directory| NetCDF files    | Grid, topography, IC, forcing          |
| MOM6 binary       | Executable      | Compiled MOM6 (solo_driver or coupled) |

## Outputs

| File / Directory    | Format     | Description                            |
|---------------------|------------|----------------------------------------|
| `ocean.stats`       | ASCII text | Per-timestep energy, CFL, sea level    |
| `ocean_daily.nc`    | NetCDF     | Daily-averaged diagnostics             |
| `ocean_month.nc`    | NetCDF     | Monthly-averaged diagnostics           |
| `RESTART/MOM.res.nc`| NetCDF     | Restart file for continuation          |
| `logfile.*.out`     | ASCII text | Per-PE log files                       |
| `available_diags.*` | ASCII text | List of all registered diagnostics     |

## Procedure

1. **Assemble run directory**:
   ```
   run_dir/
   ├── MOM_input
   ├── MOM_override      (optional)
   ├── input.nml
   ├── diag_table
   ├── MOM6              (binary, or symlink)
   └── INPUT/
       ├── ocean_hgrid.nc
       ├── topog.nc
       ├── MOM_IC.nc
       ├── forcing_*.nc
       └── vcoord.nc
   ```

2. **Critical MOM_input parameters to verify**:
   ```fortran
   DT = 900.0           ! Must satisfy CFL: DT < dx / c_max
   DT_THERM = 3600.0    ! Typically 1-4× DT
   NK = 75              ! Must match vertical coordinate file
   NIGLOBAL = 360       ! Must match grid file
   NJGLOBAL = 180       ! Must match grid file
   ```

3. **Run the model**:
   ```bash
   # Using the wrapper tool
   python run_mom6.py --run-dir ./run_dir --binary ./MOM6 -n 16 \
     --json-report run_report.json

   # Or directly
   cd run_dir
   mpirun -np 16 ./MOM6
   ```

4. **Monitor progress** via `ocean.stats`:
   ```bash
   tail -f ocean.stats
   # Watch for: increasing energy, CFL > 0.5, truncation events
   ```

## Verification

- [ ] `ocean.stats` shows stable or decreasing energy over time
- [ ] Maximum CFL remains < 0.5 (safe) or < 0.8 (acceptable)
- [ ] No velocity truncation events (Truncs = 0)
- [ ] Sea level is physically reasonable (|SL| < 2 m for global)
- [ ] Restart files written in `RESTART/`
- [ ] Diagnostic NetCDF files created with expected variables
- [ ] No "FATAL" or "WARNING" messages in log files

## Traps

| Trap ID | Symptom                    | Cause                         | Fix                         |
|---------|----------------------------|-------------------------------|-----------------------------|
| dt_014  | Immediate crash            | DT specified in hours not seconds | DT_s = DT_h × 3600     |
| -       | CFL blowup after few steps | DT too large for grid spacing | Reduce DT or use coarser grid |
| -       | Segfault on startup        | Domain decomposition mismatch | Ensure NI×NJ divisible by nprocs |
| -       | Hangs at initialization    | MPI processes can't communicate | Check network, try fewer PEs |
| -       | "TOPO_FILE not found"      | File not in INPUT/ directory  | Move file or fix parameter  |
| -       | Massive memory usage       | domains_stack_size too small  | Increase in fms_nml         |

## Example

```bash
# Full execution sequence
cd /path/to/run_dir

# Preflight check
python run_mom6.py --run-dir . --binary ./MOM6 -n 4 --skip-run

# If preflight passes, run
python run_mom6.py --run-dir . --binary ./MOM6 -n 4 --json-report report.json

# Check results
python -c "
import json
r = json.load(open('report.json'))
print('Return code:', r['execution']['returncode'])
print('Elapsed:', r['execution']['elapsed_seconds'], 's')
print('Final CFL:', r['output']['stats'].get('max_cfl', 'N/A'))
print('Final energy:', r['output']['stats'].get('final_energy', 'N/A'))
"
```
