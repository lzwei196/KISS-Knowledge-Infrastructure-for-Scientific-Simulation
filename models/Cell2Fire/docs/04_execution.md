# Stage 4: Model Execution

## Purpose

Run the Cell2Fire binary to simulate wildfire spread. This stage performs preflight checks, executes the simulation, and validates outputs.

## Inputs

| Input | Description |
|-------|-------------|
| Cell2Fire binary | Compiled `Cell2Fire` executable |
| Instance folder | Directory with all rasters, weather, lookup table, and optional ignitions |
| CLI arguments | Model choice, number of simulations, threads, etc. |

## Outputs

| Output | Flag Required | Description |
|--------|---------------|-------------|
| `Messages/MessagesFile{N}.csv` | `--output-messages` | Cell-to-cell fire propagation records |
| `Grids/Grids{N}/ForestGrid{P}.csv` | `--grids` | Grid state at each period |
| `Grids/Grids{N}/FinalGrid.csv` | `--final-grid` | Final burned/unburned state |
| `RateOfSpread/ROSFile{N}.csv` | `--out-ros` | Rate of spread per cell (m/min) |
| `Intensity/IntensityFile{N}.csv` | `--out-intensity` | Byram fire intensity (kW/m) |
| `FlameLength/FLFile{N}.csv` | `--out-fl` | Flame length (m) |
| `CrownFire/CrownFile{N}.csv` | `--out-crown` | Crown fire state (0/1) |
| `ignition_and_weather_log.csv` | always | Log of ignition points and weather per simulation |

## Procedure

### Step 1: Compile the binary (if not already done)

```bash
cd Cell2Fire/
sudo apt install g++ libboost-random-dev libtiff-dev
make
```

### Step 2: Prepare output directory

The output folder must exist and be **empty**:

```bash
mkdir -p results
rm -rf results/*
```

### Step 3: Run with basic flags

**Scott & Burgan (simplest case)**:
```bash
./Cell2Fire \
    --input-instance-folder ../data/ScottAndBurgan/Hom_Fuel_101_40x40-asc \
    --output-folder results \
    --sim S --nsims 5 --seed 123 --nthreads 4 \
    --output-messages --final-grid --ignitionsLog
```

**Canadian FBP with crown fire**:
```bash
./Cell2Fire \
    --input-instance-folder ../data/CanadianFBP/dogrib-asc \
    --output-folder results \
    --sim C --nsims 10 --seed 456 --nthreads 8 \
    --cros --output-messages --final-grid --out-ros --out-intensity
```

**Vilopriu 2013 (realistic case)**:
```bash
./Cell2Fire \
    --input-instance-folder ../data/ScottAndBurgan/Vilopriu_2013-asc \
    --output-folder results \
    --sim S --nsims 20 --seed 123 --nthreads 8 \
    --fmc 66 --scenario 2 --cros \
    --output-messages --final-grid --out-ros --ignitionsLog
```

### Step 4: Using the Python wrapper

```python
from run_cell2fire import run_cell2fire

result = run_cell2fire(
    binary="../Cell2Fire/Cell2Fire",
    instance_folder="../data/ScottAndBurgan/Vilopriu_2013-asc",
    output_folder="./results",
    model="S",
    nsims=10,
    seed=123,
    nthreads=4,
    fmc=66,
    scenario=2,
    cros=True,
    out_ros=True,
)

if result["returncode"] == 0:
    print(f"Success! Runtime: {result['runtime_s']}s")
else:
    print(f"Failed: {result['stderr'][:500]}")
```

### Step 5: Monitor execution

- Cell2Fire prints simulation progress to stdout.
- For large landscapes (>500×500 cells), each simulation can take minutes.
- Use `--nthreads` to parallelize across simulations.
- Redirect output for logging: `Cell2Fire ... > log.txt 2>&1`

## Verification

1. **Return code**: Binary exits with code 0.
2. **Output folder populated**: Messages, Grids, etc. directories exist.
3. **File counts**: Number of output files matches `--nsims`.
4. **Non-empty outputs**: Messages files contain fire propagation data.
5. **Final grids**: Contain mix of 0 (unburned) and 1 (burned) values.
6. **Ignition log**: Lists the ignition cell and weather file for each simulation.

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Output folder not empty | Silent errors, mixed results | Always `rm -rf results/*` first |
| Binary not executable | "Permission denied" | `chmod +x Cell2Fire` |
| Missing libtiff | "error while loading shared libraries: libtiff" | `apt install libtiff-dev` |
| Missing libboost | "cannot find -lboost_random" (compile time) | `apt install libboost-random-dev` |
| Fire-Period-Length > Weather-Period-Length | Silently clamped, unexpected time steps | Keep Fire-Period-Length ≤ Weather-Period-Length |
| --nsims too large with --grids | Disk space exhaustion | Use --final-grid instead of --grids |
| --nthreads > CPU cores | Slower due to oversubscription | Match to available cores |
| No ignition possible | Fire never starts, empty outputs | Check fuel at ignition cell is burnable |

## Example

Running 113 simulations across all 4 models (from the official test suite):

```bash
for model in fbp kitral sb portugal; do
    if [ "$model" == "fbp" ]; then
        args="--cros"; sim="C"
    elif [ "$model" == "sb" ]; then
        args="--scenario 1"; sim="S"
    elif [ "$model" == "portugal" ]; then
        args="--scenario 1"; sim="P"
    elif [ "$model" == "kitral" ]; then
        args=""; sim="K"
    fi
    mkdir -p test_results/$model
    ./Cell2Fire --input-instance-folder test/model/$model-asc \
        --output-folder test_results/$model \
        --nsims 113 --output-messages --grids --out-intensity \
        --sim $sim --seed 123 --ignitionsLog $args > test_results/$model/log.txt
done
```
