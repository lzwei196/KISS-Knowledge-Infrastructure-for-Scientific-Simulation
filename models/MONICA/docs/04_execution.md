# Stage 4: Model Execution

## Purpose

Run the MONICA simulation using the `monica-run` CLI binary. This stage covers
building the binary, setting up the runtime environment, and executing the model.

## Inputs

| File         | Description                                       |
|--------------|---------------------------------------------------|
| sim.json     | Simulation configuration (dates, switches, output)|
| site.json    | Site and soil profile parameters                  |
| crop.json    | Crop rotation and management                      |
| climate.csv  | Daily meteorological forcing                      |
| monica-run   | Compiled binary                                   |

## Outputs

| File         | Description                                |
|--------------|--------------------------------------------|
| out.csv      | Model output (configurable columns/events) |
| stderr       | Diagnostic messages                         |

## Procedure

### Step 1: Build the binary

```bash
# Clone all three repositories as siblings
mkdir monica-master && cd monica-master
git clone https://github.com/zalf-rpm/monica.git
git clone https://github.com/zalf-rpm/monica-parameters.git
git clone https://github.com/zalf-rpm/mas-infrastructure.git

# Create symlink for shared libraries
cd monica
ln -sf ../mas-infrastructure/src mas_cpp_misc

# Build
mkdir _cmake_release && cd _cmake_release
cmake -DCMAKE_BUILD_TYPE=Release ..
make -j$(nproc)
```

The binary `monica-run` will be in `_cmake_release/`.

### Step 2: Set environment

```bash
export MONICA_PARAMETERS=/path/to/monica-parameters
```

This is **mandatory**. Without it, `"include-from-file"` references in JSON
config files will fail silently, producing zero-output runs.

### Step 3: Run the model

```bash
./monica-run -o /path/to/out.csv /path/to/sim.json
```

### Step 4: Verify output

Check that `out.csv` was created, is non-empty, and contains expected columns.

## CLI Reference

```
monica-run [OPTIONS] path-to-sim.json

OPTIONS:
  -d, --debug                   Show debug outputs
  -sd, --start-date DATE        Override climate start date (YYYY-MM-DD)
  -ed, --end-date DATE          Override climate end date (YYYY-MM-DD)
  -op, --path-to-output DIR     Output directory
  -o, --path-to-output-file F   Output file path
  -c, --path-to-crop FILE       Override crop.json path
  -s, --path-to-site FILE       Override site.json path
  -w, --path-to-climate FILE    Override climate.csv path
  -m, --write-multiple-output-files  One file per output section
```

## sim.json Output Configuration

The `output` section in `sim.json` controls what gets written:

```json
{
  "output": {
    "write-file?": true,
    "path-to-output": "./",
    "file-name": "out.csv",
    "csv-options": {
      "include-header-row": true,
      "include-units-row": true,
      "csv-separator": ","
    },
    "events": [
      ["daily", "Date", "Crop", "Yield", "LAI", "Act_ET", "Precip",
       ["Mois", [1,20]], ["STemp", [1,5]]]
    ]
  }
}
```

### Event types

| Type          | Trigger                   | Use case                    |
|---------------|---------------------------|-----------------------------|
| daily         | Every day                 | Full timeseries             |
| monthly       | End of month              | Monthly aggregations        |
| yearly        | End of year               | Annual summaries            |
| run           | End of simulation         | Total run statistics        |
| crop          | Each harvest event        | Per-crop yield summary      |
| YYYY-MM-DD    | Specific date             | Sampling dates              |

## Verification

- [ ] Binary exists and is executable
- [ ] `MONICA_PARAMETERS` points to valid directory with `crops/` and `general/`
- [ ] `sim.json` is valid JSON (no trailing commas)
- [ ] All file references in sim.json resolve
- [ ] Output file created and non-empty
- [ ] Data rows present (not just headers)

## Traps

| ID  | Symptom                           | Cause                                | Fix                         |
|-----|-----------------------------------|--------------------------------------|-----------------------------|
| —   | "file not found" error            | MONICA_PARAMETERS not set            | Export env variable          |
| —   | Empty output file                 | sim.json output events misconfigured | Check events array syntax    |
| —   | JSON parse error at startup       | Trailing comma in JSON               | Remove trailing comma        |
| —   | Segfault on start                 | Missing mas_cpp_misc symlink         | Create symlink               |
| —   | "No climate data" error           | Date range outside climate.csv range | Align start/end dates        |

## Example

```bash
# Using the wrapper tool
python run_monica.py \
    --binary /path/to/monica-run \
    --sim-json /path/to/sim.json \
    --output /path/to/out.csv \
    --parameters-dir /path/to/monica-parameters \
    --timeout 300
```
