# Stage 4: Execution

## Purpose

Run the PHREEQC binary with correct arguments, handle errors, and verify successful
completion. This stage covers building the binary, running simulations, and interpreting
runtime diagnostics.

## Inputs

| Input            | Format  | Required | Source                    |
|------------------|---------|----------|---------------------------|
| PHREEQC binary   | ELF     | Yes      | Build or pre-compiled      |
| Input file       | .pqi    | Yes      | Stages 1-3                 |
| Database file    | .dat    | Yes      | PHREEQC distribution       |

## Outputs

| Output           | Format       | Description                          |
|------------------|-------------|--------------------------------------|
| Full output      | .pqo text   | Complete speciation and mass balance |
| Selected output  | .sel TSV    | Tab-delimited user-selected columns  |
| Screen log       | text        | Runtime progress and errors          |
| phreeqc.log      | text        | Diagnostic log                       |

## Procedure

### 4.1 Building PHREEQC

```bash
cd source/repo
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
# Binary at: build/phreeqc
```

Verify build:
```bash
./phreeqc --version  # or just run without args
```

### 4.2 Running a Simulation

Basic execution:
```bash
./phreeqc input.pqi output.pqo database/phreeqc.dat
```

With screen log capture:
```bash
./phreeqc input.pqi output.pqo database/phreeqc.dat screen.log
```

Using the wrapper tool:
```bash
python3 ki/tools/run_phreeqc.py \
    --binary ./build/phreeqc \
    --input model.pqi \
    --output model.pqo \
    --database database/phreeqc.dat \
    --timeout 3600
```

### 4.3 Runtime Diagnostics

PHREEQC prints iteration progress to screen/log. Key indicators:

| Message                    | Meaning                                      |
|----------------------------|----------------------------------------------|
| "Reading input data..."    | Parsing input file                           |
| "Beginning of batch-..."   | Starting equilibrium calculations             |
| "Using solution X"         | Processing solution number X                 |
| "Iterations: N"            | Newton-Raphson converged in N iterations      |
| "WARNING: ..."             | Non-fatal issue (check carefully)            |
| "ERROR: ..."               | Fatal error (simulation stops)               |
| "Numerical method failed"  | Solver did not converge                      |

### 4.4 Common Exit Codes

| Code | Meaning                                          |
|------|--------------------------------------------------|
| 0    | Success                                          |
| 1    | Input error (syntax, missing keyword, etc.)      |
| 2    | Database error (missing element, bad format)     |
| >2   | Runtime error (convergence failure, etc.)        |

### 4.5 Performance Considerations

- Simple speciation: < 1 second
- Equilibrium + phases: 1-10 seconds
- 1-D transport (100 cells, 1000 shifts): 1-60 minutes
- Inverse modeling: 1-30 minutes depending on complexity
- Kinetics with CVODE: varies widely (minutes to hours)

For large transport simulations, SELECTED_OUTPUT significantly increases file I/O.
Consider reducing print frequency with `-print_frequency`.

## Verification

1. Exit code = 0
2. Output file exists and is non-empty
3. No "ERROR" lines in output
4. Check charge balance in output: should be < 5% for all solutions
5. For transport: verify all cells were processed (check cell count in output)

## Traps

| Trap | Description | Detection | Fix |
|------|-------------|-----------|-----|
| dt_007 | Solver convergence failure | "Numerical method failed" | Simplify initial conditions, add step-wise reactions |
| dt_008 | Memory overflow in transport | Segfault or OOM kill | Reduce cells or print_frequency |
| dt_011 | Wrong database path | "Could not open database" | Verify path is absolute or relative to CWD |
| dt_012 | Input file encoding issues | "Unexpected character" | Ensure UTF-8 or ASCII, no BOM |

## Example

Full execution workflow:
```bash
# 1. Build
cd /path/to/phreeqc3/source/repo
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release && make -j4

# 2. Test with example 1
./phreeqc ../examples/ex1 ex1.out ../database/phreeqc.dat

# 3. Check success
if [ $? -eq 0 ]; then
    echo "Success. Output size: $(wc -c < ex1.out) bytes"
    head -20 ex1.out
else
    echo "FAILED"
    tail -20 ex1.out
fi

# 4. Run custom simulation
./phreeqc my_model.pqi my_model.pqo ../database/wateq4f.dat screen.log
grep "ERROR" my_model.pqo || echo "No errors found"
```
