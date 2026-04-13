# Stage 3: Job Options and Parameter Configuration

## Purpose

Configure the CLASSIC job options file and select the appropriate run parameters namelist. The job options file is the master control file that determines what the model simulates, which input files it reads, and what output it produces.

## Inputs

| Input | Description |
|-------|-------------|
| Job options template | `configurationFiles/template_job_options_file.txt` |
| Run parameters | `configurationFiles/template_run_parameters.txt` (or peatlands/shrubs variants) |
| Output variable descriptors | `configurationFiles/outputVariableDescriptors.xml` |
| Paths to met files | From Stage 1 |
| Path to init file | From Stage 2 |

## Outputs

- Modified `job_options_file.txt` with correct paths and switches
- Correct `run_parameters.txt` selection
- Copy of init_file as `rs_file.nc` (restart file to be overwritten)

## Procedure

### 1. Select run configuration

| Configuration | ctem_on | Typical use |
|--------------|---------|-------------|
| Physics only (CLASS) | .false. | Energy/water balance only, prescribed vegetation |
| Biogeochemistry (CLASS+CTEM) | .true. | Full carbon cycle, dynamic LAI |
| With fire | dofire=.true. | Requires POPD + LGHT files |
| With competition | PFTCompetition=.true. | Dynamic PFT composition |
| With land use change | lnduseon=.true. | Requires LUC file |

### 2. Set meteorological options

```fortran
readMetStartYear = 1991   ! First year in met files
readMetEndYear = 2017      ! Last year in met files
metLoop = 1                ! Number of loops over met (>1 for spinup)
leap = .true.              ! True if met data includes Feb 29
```

### 3. Set file paths

```fortran
metFileFss = 'path/to/dswrf.nc'
metFileFdl = 'path/to/dlwrf.nc'
metFilePre = 'path/to/pre.nc'
metFileTa = 'path/to/tmp.nc'
metFileQa = 'path/to/spfh.nc'
metFileUv = 'path/to/wind.nc'
metFilePres = 'path/to/pres.nc'
init_file = 'path/to/init_file.nc'
rs_file_to_overwrite = 'path/to/rsFile.nc'
runparams_file = 'configurationFiles/template_run_parameters.txt'
```

**CRITICAL**: `rs_file_to_overwrite` is **overwritten** by the model. Always copy init_file to create it:
```bash
cp init_file.nc rsFile.nc
```

### 4. Set physics switches for field data

```fortran
IDISP = 1     ! Include displacement height (field data)
IZREF = 1     ! Surface at ground level (field data)
ZRFH = 10.0   ! Measurement height for T, Q (meters)
ZRFM = 10.0   ! Measurement height for wind (meters)
ZBLD = 50.0   ! Blending height
ISLFD = 0     ! Stability correction scheme
IPCP = 1      ! Precip partitioning (1=0C cutoff)
ITC = 1       ! Bisection iteration (NOT Newton-Raphson=2)
ITCG = 1
ITG = 1
```

### 5. Set output options

```fortran
output_directory = 'outputFiles'
xmlFile = 'configurationFiles/outputVariableDescriptors.xml'
domonthoutput = .true.
JMOSTY = 1991           ! Start year for monthly output
doAnnualOutput = .true.
```

### 6. Handle spin-up (if using CTEM)

For carbon pool equilibration:
```fortran
metLoop = 50            ! Cycle over 20 years of met, 50 times = 1000 model years
spinfast = 5            ! Accelerate soil C (up to 10)
```
Then for transient run:
```fortran
metLoop = 1
spinfast = 1            ! Normal rate, enables carbon balance check
```

## Verification

```bash
# Check that all referenced files exist
grep -oP "(?<=')[^']+\.nc" job_options_file.txt | while read f; do
    test -f "$f" && echo "OK: $f" || echo "MISSING: $f"
done

# Check restart file is a copy of init
cmp init_file.nc rsFile.nc && echo "rsFile is init copy: OK"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| rs_file_to_overwrite = init_file | Init file gets overwritten, losing original state | Copy init to separate rs file |
| ZRFH < canopy height | Model crashes (division by zero in flux calc) | Set ZRFH > max vegetation height |
| ITC/ITCG/ITG = 2 | Newton-Raphson instabilities, convergence failure | Use 1 (bisection) |
| metLoop too low for spinup | Carbon pools not equilibrated | Use metLoop >= 30 for CTEM |
| Wrong PFT count in params vs init | Model crashes on dimension mismatch | Ensure ican, icc match between files |
| fixedYearLUC = -9999 with lnduseon = .true. | Undefined behavior | Use valid year or set lnduseon = .false. |

## Example

Minimal point simulation setup:
```bash
# 1. Copy template
cp configurationFiles/template_job_options_file.txt my_job_options.txt

# 2. Edit paths (use sed or manual editing)
# 3. Copy init to restart
cp init_file.nc rsFile.nc

# 4. Run
bin/CLASSIC_serial my_job_options.txt 0/0
```
