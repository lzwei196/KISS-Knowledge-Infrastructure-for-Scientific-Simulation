# Stage 6: Model Execution

## Purpose

Execute the Delft3D simulation using the DIMR (Deltares Integrated Model Runner)
framework. DIMR orchestrates single or coupled component runs (flow, waves,
water quality, real-time control) and handles MPI parallelization.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| DIMR config | .xml | User / template | Component orchestration |
| MDU file | .mdu | Stage 5 | D-Flow FM configuration |
| MDF file | .mdf | Stage 5 | Delft3D-FLOW configuration |
| Grid file | _net.nc / .grd | Stage 1 | Computational mesh |
| Forcing files | .wnd, .amp, etc. | Stage 3 | Meteorological forcing |
| Boundary files | .ext, .bc, .pli | Stage 4 | Boundary conditions |
| Delft3D binaries | dimr, dflowfm | Build / Docker | Executable engines |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Map output | _map.nc | Spatial fields at regular intervals |
| History output | _his.nc | Time series at observation points |
| Restart file | _rst.nc | Full model state for continuation |
| Diagnostic output | .dia | Runtime diagnostics and warnings |
| Log file | simulation.log | Console output |

## Procedure

### 1. Preflight Checks

Before execution, verify:
- All input files referenced in MDU/MDF exist
- Grid file is readable and has valid topology
- Boundary files are complete and consistent
- Binary is executable and compatible with system libraries
- Disk space is sufficient for output

```bash
python ki/tools/run_delft3d.py \
  --dimr_config dimr_config.xml \
  --binary_dir /path/to/install_all/lnx64/bin \
  --work_dir /path/to/simulation \
  --nproc 4
```

### 2. Sequential Execution

```bash
# Using run_dimr.sh wrapper
cd /path/to/simulation
/path/to/bin/run_dimr.sh -m dimr_config.xml

# Direct execution
dimr dimr_config.xml
```

### 3. Parallel Execution (MPI)

```bash
# Split grid for N processes (automatic by DIMR for D-Flow FM)
mpirun -np 4 dimr dimr_config.xml

# Using run_dimr.sh with process count
/path/to/bin/run_dimr.sh -m dimr_config.xml -c 4
```

### 4. Docker Execution

```bash
docker run -v $(pwd):/sim -w /sim \
  localhost/delft3d:oneapi-2024 \
  dimr dimr_config.xml
```

### 5. Monitoring

- Check log file for progress: `tail -f simulation.log`
- Look for timestep progress: "timestep N of M" or percentage
- Monitor output file growth: `ls -la output/*.nc`
- Check for CFL violations in .dia file

## Verification

After execution, verify:

1. **Return code = 0**: non-zero indicates failure
2. **Output files exist**: _map.nc and _his.nc should be in output directory
3. **Output has expected timesteps**: check time dimension in NetCDF
4. **No NaN/Inf values**: numerical blowup indicator
5. **Water level range is physical**: typically -5 to +10 m for tidal simulations
6. **Mass balance**: total water volume should be conserved (within numerical tolerance)

```python
import netCDF4 as nc
ds = nc.Dataset("output/model_his.nc")
s1 = ds.variables["s1"][:]
print(f"Water level range: [{s1.min():.3f}, {s1.max():.3f}] m")
print(f"NaN count: {np.isnan(s1).sum()}")
ds.close()
```

## Traps

1. **LD_LIBRARY_PATH not set**: DIMR needs shared libraries (Intel MPI, MKL, NetCDF).
   If `run_dimr.sh` is not used, you must set LD_LIBRARY_PATH manually:
   ```bash
   export LD_LIBRARY_PATH=/path/to/install_all/lnx64/lib:$LD_LIBRARY_PATH
   ```

2. **MPI version mismatch**: Delft3D compiled with Intel MPI may not work with
   OpenMPI or MPICH. Use the same MPI implementation as compilation.

3. **CFL violation → blowup**: if CFL > 1, the simulation becomes unstable.
   Symptoms: water levels growing exponentially, NaN values, "divergence" in log.
   Fix: reduce DtMax or coarsen the grid.

4. **Tunit confusion (dt_008)**: all times (TStart, TStop, DtUser, output intervals)
   are in units of Tunit. If Tunit=M (minutes) and TStop=86400, you get 60 days,
   not 1 day. Check Tunit FIRST when debugging wrong simulation duration.

5. **Output directory must exist**: D-Flow FM does NOT create the output directory.
   If `OutputDir = output` and the `output/` directory doesn't exist, the
   simulation crashes silently.

6. **Disk space**: a 30-day D-Flow FM simulation with 10,000 elements outputting
   every hour produces ~500 MB of map output. Large domains with short output
   intervals can produce terabytes.

## Example

```xml
<!-- Minimal dimr_config.xml for D-Flow FM only -->
<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<dimrConfig>
  <documentation>
    <fileVersion>1.3</fileVersion>
  </documentation>
  <control>
    <start name="DFlowFM"/>
  </control>
  <component name="DFlowFM">
    <library>dflowfm</library>
    <workingDir>dflowfm</workingDir>
    <inputFile>model.mdu</inputFile>
  </component>
</dimrConfig>
```
