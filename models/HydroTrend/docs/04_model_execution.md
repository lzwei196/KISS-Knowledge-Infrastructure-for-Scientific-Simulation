# Stage 4: Model Execution

## Purpose

Build the HydroTrend binary from source (if needed) and execute the model
with prepared input files.

## Inputs

- HydroTrend source code (C files + CMakeLists.txt)
- `{PREFIX}.IN` — main input file (from Stage 3)
- `{PREFIX}0.HYPS` — hypsometry file (from Stage 2)
- Optional: `{PREFIX}.CLIMATE` — daily climate override
- Optional: `{PREFIX}.QUAKE` — earthquake events

## Outputs

- HydroTrend binary (`hydrotrend`)
- All output files in the specified output directory (see Stage 5)
- `{PREFIX}.LOG` — execution log

## Procedure

### Step 1: Build from source

```bash
cd /path/to/hydrotrend/source/repo
mkdir -p _build && cd _build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

**Dependencies**:
- CMake >= 3.0
- C compiler (gcc or clang)
- bmi-c library (optional — build may succeed without it)
- Math library (-lm, usually automatic)

**If bmi-c is not found**: The build may fail with
`Could not find bmi-c`. You can:
1. Install bmi-c from https://github.com/csdms/bmi-c
2. Or disable BMI and build just the core library

### Step 2: Prepare directory layout

```
work_dir/
├── input/
│   ├── HYDRO.IN
│   └── HYDRO0.HYPS
└── output/          # will be created by model
```

### Step 3: Execute

```bash
./hydrotrend --in-dir=./input --out-dir=./output --prefix=HYDRO
```

**Alternative (positional args)**:
```bash
./hydrotrend HYDRO ./input
```

### Step 4: Check execution

- Check return code: 0 = success
- Check `{PREFIX}.LOG` for warnings/errors
- Verify output files exist and have content

## Verification

- [ ] Binary compiles without errors
- [ ] Input files are in the correct directory
- [ ] Output directory is writable
- [ ] Model completes without crash (exit code 0)
- [ ] Output files are non-empty
- [ ] Log file shows no ERROR messages
- [ ] Runtime is reasonable (1000 years ~ seconds to minutes)

## Traps

### bmi-c dependency
The CMakeLists.txt links against bmi-c. If not installed system-wide,
you may need to build it from source first or modify CMakeLists.txt to
remove the dependency (the standalone executable can work without it).

### Input file naming
The model looks for `{PREFIX}.IN` (exact case). On case-sensitive
filesystems, `hydro.in` will not be found if prefix is `HYDRO`.

### Output directory must exist in input file
The output directory specified in HYDRO.IN line 3 must exist AND be
writable. The model does not create it automatically.

### Memory for long simulations
Simulations > 10,000 years may require significant memory for random
number arrays. The model pre-allocates `maxran` (2200) random numbers
per year.

### Floating-point errors
NaN in Qs typically indicates:
- Qbar = 0 (no mean discharge — check precipitation)
- Division by zero in sediment formula
- Invalid C exponent from extreme Qsbar values
The model prints diagnostic NaN messages to stderr.

## Example

```bash
# Using the built-in test case
cd /path/to/hydrotrend/source/repo
mkdir -p _build && cd _build && cmake .. && make
cd ../data/input
../../_build/hydrotrend --in-dir=. --out-dir=./HYDRO_OUTPUT --prefix=HYDRO

# Verify output
wc -l HYDRO_OUTPUT/HYDROASCII.Q
# Expected: 365000 lines for 1000 years × 365 days
```

## Using run_hydrotrend.py wrapper

```bash
python run_hydrotrend.py \
    --source-dir /path/to/source/repo \
    --in-dir ./input \
    --out-dir ./output \
    --prefix HYDRO \
    --timeout 600
```

The wrapper handles build, execution, and output validation in one step.
