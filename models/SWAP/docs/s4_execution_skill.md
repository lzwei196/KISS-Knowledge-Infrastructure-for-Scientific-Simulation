# S4: SWAP Model Execution

## Purpose
Run the SWAP binary with validated input files and verify successful completion through output file checks and water balance closure.

## Inputs
- **SWAP binary**: Compiled executable (builddir/swap)
- **Working directory**: Contains swap.swp, .met, .crp, .dra files
- **swap.swp**: Main configuration file referencing all other inputs

## Outputs
- SWAP output files (result.blc, result.inc, result.vap, etc.)
- Exit code: 100 on normal completion; a fatal input error can also exit 0, so the
  exit code alone proves nothing (see step 4)
- Runtime log

## Procedure
1. **Preflight checks**:
   - Binary exists and is executable
   - All referenced input files exist (parse .swp for METFIL, CROPFIL, DRFIL, BBCFIL)
   - All filenames are lowercase (Linux requirement)
   - .swp file parses without obvious errors (matching dates, valid ranges)

2. **Execute SWAP**:
   ```bash
   cd /path/to/case/
   /path/to/swap            # reads swap.swp
   /path/to/swap other      # reads other.swp (first argument; '.swp' added)
   ```
   SWAP reads the `.swp` named by its first argument, or `swap.swp` when there is none, from
   the current directory. On Linux it lowercases that name, so use lowercase file names.
   `tools/run_swap.py --swp-file NAME.swp` passes the name for you.

3. **Monitor execution**:
   - Typical runtime: 1-30 seconds for single-point multi-year simulations
   - SWAP writes to stdout: water balance or day numbers (if SWSCRE > 0)
   - Check stderr for Fortran runtime errors

4. **Post-execution validation**:
   - Success = exit code 0 or 100 AND ` Swap normal completion!` as the LAST non-blank
     stdout line, exactly (an echoed PROJECT text with that phrase is not proof)
     (`run_swap.swap_run_succeeded()`); a `*.ok` file is not proof
   - Verify output files exist and are non-empty: `run_swap.py` fails when any
     output the .swp switches on is missing or empty, looked for at
     PATHWORK + OUTFIL + ext (.blc if SWBLC=1; .bal/.wba/.inc unless switched
     off, they default to 1; .vap if SWVAP=1; .sba only if SWSOLU=1 and SWSBA=1;
     .tem only if SWHEA=1 and SWATE=1)
   - Check .blc water balance closure: |Sum_In - Sum_Out| should be small
   - Check for a <OUTFIL>.dwb file (water balance deviation exceeded CRITDEVMASBAL;
     SWAP keeps running, `run_swap.py` prints a WARNING)

## Verification
```bash
# Check binary
file /path/to/swap  # Should show ELF executable
./swap              # Should run (will fail gracefully if no swap.swp)

# Check outputs after run
ls -la result.blc result.inc result.vap
grep "Sum" result.blc  # Water balance sums

# Check for errors
ls *.dwb 2>/dev/null && echo "WARNING: balance deviations found"
```

## Traps

### TRAP 1: SWAP reads its .swp from CWD
SWAP reads the `.swp` named by its first command-line argument (`.swp` added when missing; the name is lowercased on Linux), or `swap.swp` when there is no argument, from the current working directory. You MUST `cd` to the case directory before running. `tools/run_swap.py --work-dir DIR --swp-file NAME.swp` does both.

### TRAP 2: Case-sensitive filenames on Linux
All file references in swap.swp must be lowercase on Linux. SWAP searches for exact filename matches. A reference to `'283.MET'` will fail if the file is `283.met`.

### TRAP 3: Fortran runtime errors
Common errors:
- "forrtl: severe (24): end-of-file during read" → Input file truncated or wrong format
- "forrtl: severe (59): list-directed I/O syntax error" → Wrong delimiter or data format
- Segfault → Array overflow (too many compartments, crop entries, etc.)

### TRAP 4: Silent wrong results
SWAP may complete successfully but produce wrong results if:
- Humidity is in wrong units (fraction vs kPa)
- Radiation is in wrong units (W/m² vs kJ/m²/d)
- Soil parameters are unrealistic (ORES > OSAT)
Always check the water balance for physical plausibility.

### TRAP 5: Output file overwrite
SWAP overwrites existing output files without warning. Rename or move previous outputs before re-running.

## Example
```bash
# Full execution workflow
cd /home/user/swap_case/hupselbrook/

# Verify inputs
ls swap.swp 283.met grassd.crp maizes.crp potatod.crp swap.dra

# Run
/path/to/builddir/swap

# Check outputs
cat result.blc | grep "Sum"
# Expected: Sum : 84.68 (In), Sum : 80.72 (Out) for Hupselbrook 2002
```
