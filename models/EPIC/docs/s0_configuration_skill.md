# Stage 0: Configuration

## Purpose

Define the experiment parameters, model paths, and simulation period for an EPIC
crop simulation. This stage produces a `config.yml` file and establishes the
workspace directory structure.

## Prerequisites

- Python 3.11 with `geo_epic_win` installed (`pip install geo_epic_win`)
- EPIC 1102 binary available (bundled in `geoEpic/assets/workspace_win/model/`)
- Target region defined (coordinates, state/county FIPS codes)

## Inputs

| Input | Format | Example |
|-------|--------|---------|
| Experiment name | string | "Iowa Corn 2015-2020" |
| EPIC binary path | file path | `./model/EPIC1102.exe` |
| Start date | YYYY-MM-DD | `2015-01-01` |
| Duration | integer years | `6` |
| Output types | list | `[ACY, DGN]` |
| Region of interest | text/shapefile | "Iowa" |

## Outputs

| Output | Format | Location |
|--------|--------|----------|
| config.yml | YAML | workspace root |
| Directory tree | directories | model/, weather/, soil/, sites/, opc/, output/, log/ |

## Procedure

1. **Initialize workspace** using the Geo-EPIC toolkit:
   ```python
   from geoEpic.core import Workspace
   # or use CLI: geo_epic init
   ```
   This copies the asset template to a new workspace directory.

2. **Edit config.yml** with experiment parameters:
   ```yaml
   EXPName: Iowa Corn 2015-2020
   EPICModel: ./model/EPIC1102.exe
   start_date: '2015-01-01'
   duration: 6
   output_types: [ACY, DGN]
   ```

3. **Verify model binary** exists and is executable:
   ```bash
   ls -la model/EPIC1102.exe
   chmod +x model/EPIC1102.exe  # Linux only
   ```

4. **Create info.csv** skeleton with site list columns:
   ```csv
   SiteID,soil,dly,opc,lat,lon
   ```

## Verification

- `config.yml` exists and is valid YAML
- `model/EPIC1102.exe` exists
- All required DAT files present in `model/`
- Directory tree created

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Python version mismatch | Import errors, numpy issues | Must use Python 3.11 exactly |
| Missing DAT files | EPIC crashes silently | Copy full model/ from assets |
| Wrong start_date format | EPICCONT.DAT parse error | Use YYYY-MM-DD with quotes |
| Duration = 0 | No simulation runs | Must be >= 1 |
| SiteID > 9 chars | Truncation in EPICRUN.DAT | Keep SiteID to 9 alphanumeric chars |

## Example

```bash
# Initialize workspace from template
geo_epic init --name iowa_corn --dest ./iowa_corn_workspace

# Edit configuration
cd iowa_corn_workspace
vim config.yml  # Set dates, region, output types

# Verify
python -c "from ruamel.yaml import YAML; print(YAML().load(open('config.yml')))"
```
