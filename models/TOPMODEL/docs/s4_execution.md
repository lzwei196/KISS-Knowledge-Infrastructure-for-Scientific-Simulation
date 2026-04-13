# Stage 4: Model Execution

## Purpose

Build the TOPMODEL binary from C source, configure the run directory,
and execute the model.

## Inputs

| Input | Description |
|-------|-------------|
| Source code | NOAA-OWP TOPMODEL repository |
| topmod.run | Configuration file pointing to data files |
| inputs.dat | Forcing time series (from Stage 1) |
| subcat.dat | TWI distribution (from Stage 2) |
| params.dat | Model parameters (from Stage 3) |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| topmod.out | Text | Detailed per-timestep model state |
| hyd.out | Text | Simulated vs observed hydrograph |
| run_bmi | Binary | Compiled executable |

## Procedure

### 1. Build

```bash
cd source/repo/src/
make clean && make
cd ..
# Binary: ./run_bmi
```

Requirements: GCC, Make, libm.

### 2. Set up run directory

The binary expects data files relative to its working directory:

```
run_dir/
  run_bmi          <- binary (or symlink)
  data/
    topmod.run     <- configuration
    inputs.dat     <- forcing
    subcat.dat     <- topographic data
    params.dat     <- parameters
```

The `topmod.run` file must reference paths relative to the run directory:
```
1
Basin Name
data/inputs.dat
data/subcat.dat
data/params.dat
topmod.out
hyd.out
```

### 3. Execute

```bash
cd run_dir/
./run_bmi
```

- No command-line arguments needed (config path is hardcoded as `./data/topmod.run`)
- Runtime: seconds for typical 10-year hourly simulations
- Output files written to paths specified in topmod.run

### 4. Check outputs

```bash
# Check topmod.out exists and has water balance
tail -5 topmod.out
# Should show: SUMP  SUMAE  SUMQ  SUMRZ  SUMUZ  SBAR  BAL

# Check hyd.out has data
wc -l hyd.out
head -5 hyd.out
```

## Verification

- [ ] Binary compiles without errors
- [ ] No segmentation faults during execution
- [ ] topmod.out contains water balance summary
- [ ] hyd.out has expected number of lines (= nstep)
- [ ] BAL (water balance residual) is small relative to SUMP
- [ ] Q values in hyd.out are non-negative and physically reasonable

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Wrong path in topmod.run | "Can't open control file" | Use relative paths from binary location |
| Config not named `data/topmod.run` | File not found | Hardcoded in main.c line 31; copy to right path |
| Binary built in wrong dir | Missing in run_dir | Copy run_bmi to run directory |
| stand_alone = 0 | No output produced | Set to 1 for standalone mode |
| nstep very large | Long runtime or memory issue | Use daily (dt=24h) instead of hourly |
| Segfault | Array overflow | Check nstep matches data lines in inputs.dat |

## Example

```bash
# Full workflow
cd /path/to/topmodel/source/repo
cd src && make clean && make && cd ..

# Set up run directory
mkdir -p run/data
cp run_bmi run/
cp data/* run/data/

# Run
cd run
./run_bmi

# Check
tail -3 topmod.out
wc -l hyd.out
```
