# Stage 4: EPIC Model Execution

## Purpose

Run the EPIC crop model binary for one or more sites using the Geo-EPIC workspace
framework. This stage handles workspace assembly, EPICCONT.DAT configuration,
parallel execution, and output collection.

## Prerequisites

- Stages 0-3 completed (config, weather, soil, operations)
- info.csv populated with site list
- All referenced .DLY, .SOL, .SIT, .OPC files exist

## Inputs

| Input | Format | Location |
|-------|--------|----------|
| config.yml | YAML | workspace root |
| info.csv | CSV | workspace root |
| Weather files | .DLY, .WP1, .WND | weather/ |
| Soil files | .SOL | soil/ |
| Site files | .SIT | sites/ |
| Operations | .OPC | opc/ |
| Model files | .DAT + .exe | model/ |

## Outputs

| Output | Format | Location |
|--------|--------|----------|
| {site}.ACY | Text | output/ |
| {site}.DGN | Text | output/ |
| Run logs | Text | log/ |

## Procedure

### Using Geo-EPIC Workspace

```python
from geoEpic.core import Workspace

ws = Workspace('config.yml')
ws.run()  # Runs all sites from info.csv
```

### Using the KI wrapper tool

```bash
python tools/run_epic_workspace.py \
  --workspace /path/to/workspace \
  --timeout 30
```

### Manual single-site execution

```bash
cd model/
# Configure EPICCONT.DAT (line 1: duration, year, month, day)
# Configure EPICRUN.DAT (site_id and flags)
# Ensure all file references are correct
./EPIC1102.exe
```

### Execution Flow (per site)

1. **Copy model directory** to cache (`/dev/shm/geo_epic_{user}/{uuid}/`)
2. **Write file references**:
   - `WDLSTCOM.DAT` → `1.DLY`
   - `WPM1USEL.DAT` → `1.WP1` with lat/lon/elev
   - `WINDUSEL.DAT` → `1.WND`
   - `SITECOM.DAT` → `{site}.SIT`
   - `SOILCOM.DAT` → `{site}.SOL`
   - `OPSCCOM.DAT` → `{site}.OPC`
3. **Write EPICRUN.DAT**: `{site_id:>9s} 1  0  0  0  1  1  1/`
4. **Execute binary** with stdin piped (handles prompts)
5. **Collect outputs** from cache to `output/`
6. **Cleanup** temp directory

### EPICCONT.DAT Configuration

Line 1: `[duration:4][year:4][month:4][day:4]`

```
   6201501011.00...
```
Means: 6 years starting 2015-01-01.

### Parallel Execution

Geo-EPIC uses `pebble` for parallel site execution:

```python
ws = Workspace('config.yml')
ws.run(num_workers=8)  # 8 parallel processes
```

Each site runs in an isolated temp directory, so concurrent execution is safe.

## Verification

1. **Return code**: EPIC should exit with code 0
2. **Output files exist**: `{site}.ACY` and `{site}.DGN` in output/
3. **Output file size > 0**: Empty files indicate failed simulation
4. **Log check**: No fatal errors in log files
5. **Quick ACY check**: `head -15 output/{site}.ACY` should show yield data

## Traps

| Trap | Symptom | Root Cause | Fix |
|------|---------|------------|-----|
| Windows .exe on Linux | Permission denied or exec format error | PE binary needs Wine | Install Wine or use Linux-compiled EPIC |
| Missing .DLY file | EPIC crashes or uses weather gen | DLY not in correct location | Check WDLSTCOM.DAT points to 1.DLY |
| EPICRUN.DAT format wrong | EPIC reads wrong site | Site ID > 9 chars or wrong flags | Keep SiteID ≤ 9 chars |
| Timeout too short | Sites never complete | Complex simulation | Increase timeout in config.yml |
| /dev/shm full | Cannot create temp dir | Too many parallel runs | Clean up old cache dirs |
| File references wrong | EPIC reads wrong files | COM.DAT files point to wrong paths | Verify all COM.DAT contents |
| EPICCONT dates don't match DLY | Uses weather generator | DLY doesn't cover period | Align DLY date range with EPICCONT |

## Example

```python
from geoEpic.core import Workspace

# Load workspace
ws = Workspace('config.yml')

# Run specific site
ws.run(site_ids=['umstead'])

# Check output
import os
for f in os.listdir('output/'):
    print(f, os.path.getsize(f'output/{f}'))
```
