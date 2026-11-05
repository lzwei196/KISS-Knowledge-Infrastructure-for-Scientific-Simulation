# S8: Batch Execution

## Purpose

Compile the DSSAT-CSM model from Fortran source code, create a batch file specifying which experiments and treatments to run, execute the model, and diagnose any runtime errors that occur.

## Prerequisites

- [ ] A Fortran compiler is installed (gfortran recommended, version >= 7.0).
- [ ] CMake is installed (version >= 3.10.0, as required by `CMakeLists.txt` line 7).
- [ ] S3-S7 completed: a valid FileX experiment file exists with all required sections.
- [ ] All referenced data files exist: `.SOL` soil profile, `.WTH` or `.WTX` weather files, cultivar files (`.CUL`, `.ECO`, `.SPE`).
- [ ] The `dssat-csm-data` repository or equivalent data directory is available at the expected path.
- [ ] You know which treatments to run and in what mode (batch, seasonal, sequence, etc.).

## Inputs

| Parameter       | Type      | Source              | Description                                           |
|-----------------|-----------|---------------------|-------------------------------------------------------|
| Source code     | Directory | Repository          | DSSAT-CSM Fortran source tree (this repository)       |
| FileX           | File      | S3-S7 outputs       | Experiment file(s) to simulate                        |
| Treatment IDs   | Integer   | User / protocol     | Which treatments from FileX to run                    |
| Run mode        | CHAR*1    | User decision       | How the model processes treatments (see mode table)   |
| Data directory  | Path      | Installation        | Location of supporting data files (.SOL, .WTH, etc.)  |

## Procedure

### Step 1: Compile DSSAT-CSM from Source

#### Step 1.1: Verify Prerequisites

Run the following commands and confirm successful output:

```bash
gfortran --version    # Must show gfortran version >= 7.0
cmake --version       # Must show CMake version >= 3.10.0
```

If gfortran is not installed:
- macOS: `brew install gcc`
- Ubuntu/Debian: `sudo apt install gfortran`
- CentOS/RHEL: `sudo yum install gcc-gfortran`

If CMake is not installed:
- macOS: `brew install cmake`
- Ubuntu/Debian: `sudo apt install cmake`

#### Step 1.2: Create Build Directory

DSSAT enforces out-of-source builds. In-source builds produce a fatal CMake error (see `CMakeLists.txt` lines 9-14).

```bash
cd /path/to/DSSAT
mkdir -p build
cd build
```

**CRITICAL**: Do NOT run `cmake` from the source directory root. The CMakeLists.txt will reject this with:
```
FATAL_ERROR: DSSAT in-source builds are not permitted.
```

#### Step 1.3: Configure with CMake

```bash
cmake ..
```

Expected output includes:
```
-- MAJOR: 4 MINOR: 8 MODEL: 5 BUILD: 41 COMMIT: <hash>
-- BRANCH: develop
```

This confirms CMake found the Fortran compiler and parsed the project definition. The version numbers come from `CMakeLists.txt` lines 22-25:
```
SET(MAJOR 4)
SET(MINOR 8)
SET(MODEL 5)
SET(BUILD 41)
```

**If CMake fails**: Check that the Fortran compiler is in your PATH. On macOS, ensure you are using Homebrew's gcc/gfortran, not Apple's clang (which lacks Fortran support).

#### Step 1.4: Compile

```bash
make -j$(nproc 2>/dev/null || sysctl -n hw.ncpu)
```

This compiles all Fortran source files and links them into the executable. The `-j` flag parallelizes compilation using all available CPU cores.

Expected result: An executable file is produced. The name follows the pattern `dscsm0XX` where XX matches the version. For v4.8.5, the executable is typically named `dscsm048`.

**Common compilation errors**:

| Error                                    | Cause                                           | Resolution                                         |
|------------------------------------------|------------------------------------------------|----------------------------------------------------|
| `gfortran: command not found`            | Compiler not installed or not in PATH          | Install gfortran; check PATH                       |
| `Error: Unresolvable reference to...`    | Missing source file or module dependency       | Ensure all source directories are present          |
| `Error: Type mismatch in argument`       | Fortran interface mismatch (compiler strictness)| Try `-fallow-argument-mismatch` flag in CMake      |
| `undefined reference to 'main'`          | Linking error                                  | Check that CSM_Main/CSM.for is included in build   |
| Multiple definition errors               | Duplicate compilation of same file             | Clean build: `rm -rf build && mkdir build`         |

#### Step 1.5: Verify the Executable

```bash
ls -la dscsm048    # or whatever the executable name is
./dscsm048         # Should print usage or wait for input
```

If the executable runs and prints model header information or waits for input, compilation succeeded.

**IMPORTANT**: After any source code changes, you must re-run `make` from the build directory. Forgetting to recompile after code changes is the most common cause of "my changes had no effect."

#### Step 1.6: The installed build carries one upstream fix (installed 2026-10-04)

`KISSPATH_HOME/DSSAT` is upstream DSSAT commit `c911455` (v4.8.5) with one local edit (`Weather/IPWTH_alt.for`, `MaxRecords`
10000 -> 40000, 2026-05-31) and one later fix from the DSSAT team: commit `605b4a03` (G. Hoogenboom, 15 March 2026, "Correct
calculation for surface layer related to immobilization"). It changes one statement in
`Soil/CENTURY_OrganicMatter/IMMOBLIMIT_C.for`: `CO2FS1(SRFC) = CO2FS1(SRFC) * REDUCFACTMIN(L)` becomes `... * REDUCFACTMIN(1)`
(line 312 before the fix, line 313 after it).

- **Why.** With Century (`MESOM = P`) that line runs in the surface-layer block, where `L` is 0, but the array starts at 1;
  every other line of the block uses 1. Our build checks array bounds (`-fbounds-check`), so such runs stopped ("Index '0' of
  dimension 1 of array 'reducfactmin' below lower bound of 1"; 110 Route B maize cells in run R0). A build without bound checks
  does not stop: it reads memory next to the array and goes on with wrong numbers from that day on. Godwin runs (`MESOM = G`,
  what `create_workdir` writes) never reach this code. In the cells that stopped, DSSAT had warned the day after the first maize
  harvest that the surface residue has an extremely low nutrient content (the CESTR warning in `WARNING.OUT`): that warning
  marks the state that reaches this line; it is not the cause.
- **Tested** (old binary against the fixed one, same inputs): all 297 DSSAT example experiments, each with Century and with
  Godwin: no run changed (288 finish in each soil model; the 9 that do not finish stop the same way with both binaries: the rice
  examples, whose installed cultivar file is broken, and one sequence example). Route B cells through a scratch copy of the
  Route B code, maize, soybean, spring wheat and winter wheat, each rainfed and irrigated (`mai_rf`, `mai_ir`, `soy_rf`,
  `soy_ir`, `swh_rf`, `swh_ir`, `wwh_rf`, `wwh_ir`; 836 runs): in all 724 runs that the old binary finished, the fixed one gave
  the same outputs, and all 111 runs that the old binary stopped at line 312 now finish. After the install the installed binary
  was checked again against the tested fixed build: equal on the 297 examples (594 of 594 pairs), on the 110 crash cells and on
  two Route B blocks. Not tested through Route B: other crops; runs with phosphorus on.
- **Not included.** The later upstream change to the same file, `37cb7e49` (thresholds `> 1.E-6` -> `> 0.0`), was left out on
  purpose; it needs its own decision. The two old binary copies `KISSPATH_HOME/DSSAT/dscsm048` and
  `KISSPATH_HOME/DSSAT/run_test/dscsm048` do NOT have the fix: use `KISSPATH_HOME/DSSAT/build/bin/dscsm048`.
- **Open points outside this fix** (separate decisions): with phosphorus on, lines 293-295 and 384-385 of the same file set two
  phosphorus flows from arrays that are never filled (and `LIM_EL` and `AMINRL(1,IEL)` there are not checked); a likely fault in
  the CERES wheat and barley code (a residue value in `CSCER.for` not kept from one day to the next; not proven) can stop a wheat
  run now and then with a floating-point error (SIGFPE), with any binary.
- **Record.** `KISSPATH_HOME/dssat_fix_record/RECORD.md` section 2; `KISSPATH_HOME/dssat_crash_fix_20261003/INSTALL_REPORT.md`.

### Step 2: Create the Batch File

#### Step 2.1: Understand Batch File Format

The batch file is a fixed-format text file that tells the CSM which experiment files and treatments to run. The file is named `DSSBatch.v48` (or any name -- the name is passed as a command-line argument).

Source reference: The CSM reads the batch file looking for the `$BATCH` header (`CSM.for` line 238), then reads experiment paths and treatment numbers from subsequent lines (`CSM.for` lines 266-277).

#### Step 2.2: Write the Batch File Header

The first line must be `$BATCH(CROP)` where CROP is the crop name (for documentation only; the model only looks for `$BATCH`).

```
$BATCH(MAIZE)
```

Comment lines start with `!` and are ignored:
```
! Directory    : /path/to/experiments
! Command Line : ./dscsm048 B DSSBatch.v48
! Crop         : Maize
```

#### Step 2.3: Write the Column Header

```
@FILEX                                                                                        TRTNO     RP     SQ     OP     CO
```

The `@FILEX` header line is required. The model reads it to locate column positions.

Column layout (from `CSM.for` lines 268-272):
- Columns 1-92: Full path to the FileX experiment file (fixed-width, padded with spaces).
- Columns 93-98: TRTNO (treatment number, I6 format).
- Columns 99-104: RP (replication number, I6 format).
- Columns 105-110: SQ (sequence number, I6 format; 0 for non-sequence runs).
- Columns 111-116: OP (option number, I6 format; 0 for default).
- Columns 117-122: CO (control option, I6 format; 0 for default).

**CRITICAL**: The FileX path occupies columns 1 through 92. The model reads the path by finding the last non-blank character position in columns 1-92, then extracts the 12-character filename from the end of that string (`CSM.for` lines 268-270). If the path is too long and exceeds 92 characters, it will be truncated, and the model will fail with a "File not found" error. This is a Fortran fixed-format string limitation.

#### Step 2.4: Write Treatment Lines

One line per treatment to simulate:

```
/full/path/to/Maize/UFGA8201.MZX                                                                    1      1      0      0      0
```

The path must be left-justified and the filename must end at or before column 92. Pad with spaces between the path and column 93.

To run multiple treatments from the same experiment:
```
/full/path/to/Maize/UFGA8201.MZX                                                                    1      1      0      0      0
/full/path/to/Maize/UFGA8201.MZX                                                                    2      1      0      0      0
/full/path/to/Maize/UFGA8201.MZX                                                                    3      1      0      0      0
```

To run treatments from different experiments:
```
/full/path/to/Maize/UFGA8201.MZX                                                                    1      1      0      0      0
/full/path/to/Maize/BRPI0202.MZX                                                                    1      1      0      0      0
```

#### Step 2.5: Batch File Validation

1. Verify every FileX path exists: `ls /full/path/to/Maize/UFGA8201.MZX`
2. Verify every treatment number exists within its FileX.
3. Verify no path exceeds 92 characters (count characters including the filename).
4. Verify the `$BATCH` header is present on the first non-comment line.

Tool reference: `create_batch_file` can automate batch file generation from a list of experiments and treatments.

### Step 3: Run the Model

#### Step 3.1: Run Modes

The model is invoked with:
```bash
./dscsm048 <RUNMODE> <BATCHFILE> [SIMCONTROL]
```

Or with explicit model specification:
```bash
./dscsm048 <MODEL> <RUNMODE> <BATCHFILE> [SIMCONTROL]
```

Source reference: `CSM.for` lines 140-199 define all run modes.

| Mode | Name            | Description                                                    | Batch File Required |
|------|-----------------|----------------------------------------------------------------|---------------------|
| A    | All treatments  | Runs all treatments in a single FileX                          | No (FileX on cmdline)|
| B    | Batch           | Runs treatments listed in batch file                           | Yes                 |
| N    | Seasonal        | Seasonal analysis (multi-year same treatment)                  | Yes                 |
| Q    | Sequence        | Rotation/sequence analysis (cycles through treatments)          | Yes                 |
| S    | Spatial         | Spatial analysis mode                                          | Yes                 |
| E    | Sensitivity     | Sensitivity analysis mode                                      | Yes                 |
| F    | Farm            | Farm model simulation                                          | Yes                 |
| C    | Command line    | Single treatment from command line                             | No                  |
| G    | Gencalc         | Genetic coefficient calculator (command line)                  | No                  |
| T    | Gencalc batch   | Genetic coefficient calculator (batch)                         | Yes                 |
| Y    | Yield forecast  | Yield forecasting mode                                         | Yes                 |
| I    | Interactive     | Interactive mode (GUI-driven)                                  | No                  |
| D    | Debug           | Debug mode (reads temp file directly)                          | No                  |
| L    | Locus           | Gene-based model                                               | Yes                 |

**Most common usage**: Mode `B` with a batch file:
```bash
./dscsm048 B DSSBatch.v48
```

**Run all treatments in one experiment**:
```bash
./dscsm048 A UFGA8201.MZX
```

**Run a specific treatment from command line**:
```bash
./dscsm048 C UFGA8201.MZX 1
```

#### Step 3.2: Execute the Model

1. Change to the working directory where data files are located (or where you want output):
```bash
cd /path/to/working/directory
```

2. Run the model:
```bash
/path/to/build/dscsm048 B DSSBatch.v48
```

3. The model will produce output to the current working directory (not the directory where the executable or FileX is located).

4. Expected behavior: The model prints progress to stdout (treatment names, dates). Each treatment runs through the DYNAMIC state machine (see Step 4). The model exits when all treatments are complete.

#### Step 3.3: Verify Successful Execution

After the model finishes:

1. Check that `Summary.OUT` exists and has data lines:
```bash
wc -l Summary.OUT     # Should have header + one line per treatment
```

2. Check for errors:
```bash
cat MODEL.ERR 2>/dev/null   # Should not exist or be empty for clean run
cat ERROR.OUT 2>/dev/null   # Runtime errors
cat WARNING.OUT 2>/dev/null # Non-fatal warnings
```

3. Check that output files were created:
```bash
ls -la Summary.OUT Overview.OUT PlantGro.OUT SoilWat.OUT
```

### Step 4: Understand the DYNAMIC State Machine

The model processes each treatment through a sequence of phases defined as integer constants in `ModuleDefs.for` lines 67-77:

```fortran
INTEGER, PARAMETER ::
    RUNINIT  = 1,    ! One-time initialization for entire run
    INIT     = 2,    ! (Will replace RUNINIT & SEASINIT; not fully implemented)
    SEASINIT = 2,    ! Seasonal initialization
    RATE     = 3,    ! Daily rate calculations
    EMERG    = 3,    ! Used for some plant processes (same value as RATE)
    INTEGR   = 4,    ! Daily integration
    OUTPUT   = 5,    ! Write daily outputs
    SEASEND  = 6,    ! End-of-season summary
    ENDRUN   = 7     ! Close all files, final cleanup
```

#### Phase Execution Order

For a single treatment:
```
RUNINIT (1)  -->  Called once at start of run
  |
  v
SEASINIT (2) -->  Called once per season (initializes weather, soil, plant)
  |
  v
[Daily loop begins]
  |
  RATE (3)   -->  Calculate daily rates: weather -> soil -> SPAM -> plant
  |
  INTEGR (4) -->  Integrate state variables forward one day
  |
  OUTPUT (5) -->  Write daily output to PlantGro.OUT, SoilWat.OUT, etc.
  |
  [If harvest/end condition met] --> SEASEND (6) --> [exit daily loop]
  [Otherwise] --> [next day] --> RATE (3)
  |
  v
SEASEND (6)  -->  Write seasonal summary to Summary.OUT
  |
  v
[If more seasons/treatments] --> SEASINIT (2)
[If done] --> ENDRUN (7)
  |
  v
ENDRUN (7)   -->  Close all files, deallocate memory
```

#### Why This Matters

- If the model crashes during RATE (3), you may have partial PlantGro.OUT output but no Summary.OUT entry for that treatment.
- If the model crashes during SEASINIT (2), no daily output files will be created for that treatment.
- If the model finishes SEASEND (6) but crashes during ENDRUN (7), Summary.OUT will have data but output files may not be properly closed.

### Step 5: Monitor Execution and Diagnose Errors

#### Step 5.1: Check MODEL.ERR

The MODEL.ERR file contains detailed error descriptions for DSSAT error codes. The model looks for this file in the executable directory first, then in the standard DSSAT path (`ERROR.for` lines 62-72).

Error format in ERROR.OUT (the runtime error log):
```
*RUN-TIME ERRORS OUTPUT FILE
<experiment info>
ERRKEY  ERRNUM  FILE  LNUM
```

Common error codes:
- Error 42: Section not found in input file (e.g., `*INITI` section missing from FileX).
- Error 28: Batch file not found or cannot be opened.
- Error 26: `$BATCH` header not found in batch file or malformed treatment line.

#### Step 5.2: Check WARNING.OUT

WARNING.OUT contains non-fatal warnings (`Warning.for`). These do not stop the simulation but indicate potential issues.

Common warnings:
- Weather data missing for specific dates.
- Soil water content adjusted (clamped).
- Planting conditions not met on specified date.
- Nutrient balance warnings.

#### Step 5.3: Common Runtime Errors

| Error                                          | Cause                                                   | Diagnosis and Resolution                                       |
|------------------------------------------------|---------------------------------------------------------|----------------------------------------------------------------|
| `SIGFPE: Floating-point exception`             | Division by zero in a calculation                       | Check soil layers: zero thickness or zero BD causes this.      |
| `File not found` / `IOSTAT error`              | FileX, .SOL, .WTH, or cultivar file path is wrong      | Verify all paths; check for Fortran string truncation.         |
| Simulation stops with no output                | Fatal error during SEASINIT; check MODEL.ERR            | Open ERROR.OUT; look for the ERRKEY and ERRNUM.                |
| Simulation hangs indefinitely                  | Auto-planting cannot find suitable date                 | Widen planting window; check IPLTI switch; verify weather data covers the planting period. |
| `Summary.OUT` exists but has -99 for all values| Simulation ran but crop never emerged or matured        | Check PlantGro.OUT for stress factors; verify planting depth and cultivar. |
| `Section *XXXXX not found`                     | Required section missing from FileX                     | Add the missing section; see S3 for FileX structure.           |
| `Error in FILEIO`                              | Temporary IO file is corrupted or locked                | Delete DSSAT48.INP and re-run.                                 |
| Model runs but yield is 0                      | Crop failed; stress too high or wrong cultivar          | See S9 for output diagnosis procedures.                        |

#### Step 5.4: Debugging Strategies

1. **Run a single treatment first**: Before running a full batch, test with one treatment using mode `C`:
   ```bash
   ./dscsm048 C UFGA8201.MZX 1
   ```

2. **Enable verbose output**: Set IDETL='D' (detail) in the simulation controls section of FileX to get maximum output detail.

3. **Check intermediate file**: The model writes a temporary file `DSSAT48.INP` during execution. If the run fails, this file contains the parsed input data that can be inspected to see what the model actually read.

4. **Binary search for errors**: If a batch with many treatments fails, bisect the batch file to identify which treatment causes the error.

### Step 6: Post-Execution Cleanup

6.1. Output files are written to the current working directory. Move or rename them before running a new simulation, as DSSAT overwrites existing output files.

6.2. The temporary file `DSSAT48.INP` can be deleted after a successful run.

6.3. If running multiple experiments in sequence (not sequence mode), save output files between runs:
```bash
./dscsm048 B DSSBatch_exp1.v48
mkdir -p results/exp1 && mv *.OUT results/exp1/

./dscsm048 B DSSBatch_exp2.v48
mkdir -p results/exp2 && mv *.OUT results/exp2/
```

## Expected Outputs

| Output                  | Location                | Verification                                         |
|-------------------------|-------------------------|------------------------------------------------------|
| dscsm048 executable     | build/ directory        | File exists and is executable                        |
| DSSBatch.v48            | Working directory       | $BATCH header present; paths valid; treatments exist |
| Summary.OUT             | Working directory       | One data line per treatment; HWAH values present     |
| PlantGro.OUT            | Working directory       | Daily growth data for each treatment                 |
| SoilWat.OUT             | Working directory       | Daily soil water data                                |
| No MODEL.ERR/ERROR.OUT  | Working directory       | Absence indicates clean run                          |

## Validation Checks

1. **Compilation**: `dscsm048` executable exists and is newer than any source file modification time.
2. **Batch file format**: `$BATCH` header exists. All FileX paths resolve to existing files. Treatment numbers exist in their FileX. Path lengths <= 92 characters.
3. **Runtime**: `Summary.OUT` has the expected number of data lines (one per treatment). No `ERROR.OUT` file created. `WARNING.OUT` contains only benign warnings.
4. **Output completeness**: For each treatment in the batch, there is a corresponding entry in `Summary.OUT` with non-(-99) values for HWAH, ADAT, and MDAT (for crops that reach maturity).

Tool reference: `check_model_errors` can automate parsing of ERROR.OUT and WARNING.OUT.

## Common Pitfalls

| Pitfall                                        | Symptom                                                 | Resolution                                                   |
|------------------------------------------------|---------------------------------------------------------|--------------------------------------------------------------|
| Forgetting to recompile after code changes     | Source changes have no effect on simulation              | Run `make` in build directory before every run after edits   |
| Batch file path > 92 characters                | `File not found` error; Fortran string truncation        | Shorten directory path; move files closer to root            |
| Wrong run mode                                 | Unexpected behavior; model reads wrong input             | Verify mode letter matches intent (B for batch, N for seasonal)|
| Running cmake in source directory              | CMake fatal error about in-source builds                 | Always create and use a separate `build/` directory          |
| Missing DSSAT data files                       | Model cannot find .SOL, .WTH, or cultivar files          | Verify DSSATPRO.v48 paths; check file existence              |
| Output files from previous run overwritten     | Lost results from earlier simulation                     | Save/rename output files before each new run                 |
| Compilation with wrong gfortran version        | Mysterious compilation errors; type mismatch warnings    | Use gfortran >= 7.0; check with `gfortran --version`        |
| Running model from wrong working directory     | Files not found; output written to unexpected location   | cd to the data directory before running the executable       |
| DSSAT48.INP locked from previous crashed run   | Model cannot write temporary file                        | Delete DSSAT48.INP manually and re-run                       |
| Batch file missing blank line at end           | Last treatment may not be read                           | Add a blank line after the last treatment entry              |
