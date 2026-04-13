# S5: Coupling Setup

## Purpose
Configure the multi-model coupling between ROMS (ocean), SWAN/WW3 (waves), and WRF (atmosphere) via MCT (Model Coupling Toolkit) or ESMF/NUOPC. This includes processor allocation, coupling intervals, SCRIP interpolation weights, and exchange field definitions.

## Inputs
| Input                  | Format     | Source             | Notes                              |
|------------------------|------------|--------------------|------------------------------------|
| ROMS grid              | NetCDF     | Stage s1           | For SCRIP weight computation       |
| SWAN grid              | Text/NetCDF| SWAN setup         | Must overlap ROMS domain           |
| WRF domain (opt.)      | NetCDF     | WPS geogrid        | For atmosphere coupling            |
| Total processor count  | Parameter  | User/HPC           | Must be partitioned across models  |

## Outputs
| Output              | Format  | Contents                                         |
|---------------------|---------|--------------------------------------------------|
| coupling.in         | Text    | MCT coupling parameters, intervals, weights file |
| SCRIP weights       | NetCDF  | Sparse matrix interpolation weights              |
| Processor layout    | In coupling.in | NnodesATM, NnodesWAV, NnodesOCN           |

## Procedure

1. **Determine processor allocation**:
   - Total processors = NnodesOCN + NnodesWAV + NnodesATM
   - ROMS: NtileI × NtileJ processors (must match ocean.in)
   - SWAN: typically needs fewer processors than ROMS
   - WRF: depends on WRF domain size
   - Example: 16 total → 8 ROMS + 4 SWAN + 4 WRF

2. **Compute SCRIP weights**:
   ```bash
   # Using COAWST's built-in SCRIP tools
   cd Lib/SCRIP_COAWST
   # Edit scrip_coawst.in with grid file paths
   ./scrip_coawst
   ```
   Or use the provided Projects/ examples as templates.

3. **Generate coupling.in**:
   ```bash
   python3 ki/tools/generate_config.py \
     --grid Sandy_roms_grid.nc \
     --application SANDY --nprocs 16 \
     --ntile-i 2 --ntile-j 4 \
     --dt 60.0 --ndtfast 30 --ntimes 43200 \
     --output-dir Projects/Sandy/ \
     --coupled --swan --wrf \
     --coupling-dt 600 \
     --nprocs-wav 4 --nprocs-atm 4
   ```

4. **Verify coupling consistency**:
   - Coupling interval must be integer multiple of all model timesteps
   - SCRIP weights file must exist and be referenced correctly

## Verification

### Processor Allocation Check
```
NnodesOCN + NnodesWAV + NnodesATM = total MPI processes
NnodesOCN = NtileI × NtileJ (from ocean.in)
```
**If these don't match, MPI will deadlock with no error message (dt_004).**

### Coupling Interval Check
```
TI_OCN2WAV (seconds) must be divisible by:
  - Ocean DT (baroclinic timestep)
  - SWAN timestep (STATIONARY or NONSTATIONARY step)

TI_ATM2OCN must be divisible by:
  - WRF time_step
  - Ocean DT
```

### SCRIP Weights Verification
```bash
ncdump -h scrip_weights.nc | grep "n_s ="
# Should show non-zero number of sparse matrix entries
```

## Traps

**dt_004: Processor count mismatch.**
If `NtileI × NtileJ ≠ NnodesOCN`, or if total processors don't match `mpirun -np N`, the model will **deadlock** — it hangs silently with no error output. This is the most common first-run failure. **Always verify: NnodesOCN = NtileI × NtileJ** and **total = NnodesOCN + NnodesWAV + NnodesATM**.

**dt_010: Non-integer coupling interval.**
If `TI_OCN2WAV = 300` seconds but ROMS `DT = 200` seconds, the coupling will miss exchange steps. ROMS proceeds to its next timestep after 200s, but the exchange was scheduled at 300s. Use intervals that are integer multiples of the longest timestep.

**SCRIP weight quality.**
If SCRIP weights are computed with insufficient grid overlap or wrong coordinate convention, regridded fields will have zeros or stripes at domain edges. Always visualize an exchanged field (e.g., SST passed from ROMS to WRF) to check for interpolation artifacts.

## Example

For 16-processor Sandy simulation (ROMS + SWAN + WRF):
```
# coupling_sandy.in
Nmodels = 3
NnodesATM = 4    ! WRF uses 4 procs
NnodesWAV = 4    ! SWAN uses 4 procs
NnodesOCN = 8    ! ROMS uses 8 procs (NtileI=2 × NtileJ=4)
                 ! Total: 4+4+8 = 16 = mpirun -np 16

TI_ATM2WAV = 600.0    ! Exchange every 10 minutes
TI_ATM2OCN = 600.0
TI_WAV2ATM = 600.0
TI_WAV2OCN = 600.0
TI_OCN2WAV = 600.0
TI_OCN2ATM = 600.0

SCRIP_COAWST_NAME = scrip_sandy_weights.nc
```
