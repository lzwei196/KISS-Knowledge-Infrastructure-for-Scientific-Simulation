# S4: Model Execution

## Purpose

Compile the OHQLib library and OHQLibTest executable, run the model on a
prepared .ohq input file, and capture runtime output for diagnostics.

## Inputs

| Input              | Source        | Description                            |
|--------------------|---------------|----------------------------------------|
| model.ohq          | Stage S3      | Complete model script                  |
| *.csv, *.txt       | Stage S1      | Forcing and loading time series        |
| resources/         | Source repo   | JSON templates and settings            |
| OHQLibTest binary  | Build         | Compiled executable                    |

## Outputs

| Output              | Location       | Description                           |
|---------------------|----------------|---------------------------------------|
| output.txt          | Working dir    | All model results (CSV)               |
| observedoutput.txt  | Working dir    | Observation comparison (CSV)          |
| stdout              | Console        | Solver progress and diagnostics       |

## Procedure

### Step 1: Build (if not already built)

```bash
# Install dependencies
sudo apt install -y qt6-base-dev libarmadillo-dev \
  liblapack-dev libblas-dev libgsl-dev libomp-dev cmake

# Build library
cd OpenHydroQual/OHQLib
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --parallel $(nproc)

# Verify build
ls -la libOHQLib.so*
```

### Step 2: Build Test Executable

The OHQLibTest CMakeLists.txt is Windows-oriented. For Linux, link directly:

```bash
cd OpenHydroQual/OHQLibTest
g++ -std=c++14 -O2 main.cpp \
  -I../aquifolium/include \
  -I../aquifolium/include/GA \
  -I../aquifolium/include/MCMC \
  -I../aquifolium/src \
  -I../ \
  -I../jsoncpp/include \
  -L../OHQLib/build \
  -lOHQLib \
  $(pkg-config --cflags --libs Qt6Core) \
  -o OHQLibTest
```

Or use the wrapper script:

```bash
python ki/tools/run_ohq.py \
  --binary ./OHQLibTest \
  --input Examples/Wet_pond/Wet_pond.ohq \
  --resources resources/ \
  --fix-paths
```

### Step 3: Run the Model

```bash
export LD_LIBRARY_PATH=OHQLib/build:$LD_LIBRARY_PATH
./OHQLibTest /path/to/model.ohq
```

Expected stdout:
```
Input file: /path/to/model.ohq
Default Template path = .../resources/
Executing script ...
Solving ...
Writing outputs in '/path/to/output.txt'
```

### Step 4: Monitor Progress

The solver prints progress during `Solve()`. Watch for:
- **"Solving ..."** - Simulation started
- **"Writing outputs ..."** - Simulation completed
- **NaN or Inf in output** - Numerical instability

### Step 5: Verify Output

```bash
# Check output file exists and has content
wc -l output.txt
head -3 output.txt

# Check for NaN values
grep -c "nan\|inf\|NaN" output.txt
```

## Verification

- Binary exits with code 0
- output.txt exists and has > 1 line
- No NaN or Inf values in output
- Simulation end time matches configuration
- Runtime is reasonable (< timeout)

## Traps

| Trap                                    | Impact | Prevention                           |
|-----------------------------------------|--------|--------------------------------------|
| Template path not resolvable            | Fatal  | Use --fix-paths or set absolute path |
| LD_LIBRARY_PATH missing libOHQLib.so    | Fatal  | Export LD_LIBRARY_PATH               |
| Missing Qt6 runtime                     | Fatal  | Install qt6-base-dev                 |
| .ohq file in different directory        | Silent | Working folder = .ohq file directory |
| Solver stalls (tight tolerance)         | Hang   | Increase nr_tolerance or timeout     |
| c_n_weight=0 with large timestep        | Fatal  | Use c_n_weight=1 for stability       |

## Example

Running the Wet Pond example:

```bash
cd OpenHydroQual

# Fix hardcoded paths
python ki/tools/run_ohq.py \
  --binary OHQLib/build/OHQLibTest \
  --input Examples/Wet_pond/Wet_pond.ohq \
  --resources resources/ \
  --fix-paths \
  --timeout 600

# Check results
head -5 Examples/Wet_pond/output.txt
```
