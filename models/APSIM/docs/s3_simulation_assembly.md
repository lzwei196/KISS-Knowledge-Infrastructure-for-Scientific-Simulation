# S3 — Simulation Assembly

## Purpose

Assemble all components (weather, soil, crop, management) into a valid .apsimx
JSON file that APSIM can execute. This stage wires together the outputs of S1
(soil) and S2 (weather) with crop and management specifications from S0.

## Inputs

| Input                | Format     | Source              |
|----------------------|-----------|---------------------|
| Weather .met file    | text file | S2 output           |
| Soil JSON fragment   | JSON      | S1 output           |
| Crop type & cultivar | string    | S0 configuration    |
| Simulation period    | dates     | S0 configuration    |
| Sowing parameters    | numeric   | S0 configuration    |
| Management rules     | text      | S0 configuration    |

## Outputs

| Output               | Format     | Description                          |
|----------------------|-----------|--------------------------------------|
| `simulation.apsimx`  | JSON      | Complete APSIM simulation file       |
| Assembly report      | JSON      | Summary with validation warnings     |

## Procedure

1. **Run the assembly tool**:
   ```bash
   python build_apsimx.py --output wheat_dalby.apsimx \
       --met-file weather/dalby.met --soil-json soil.json \
       --crop Wheat --cultivar Hartog --population 100 \
       --start 1992-01-01 --end 1995-12-31 \
       --auto-sow --sow-window-start "1-May" --sow-window-end "1-Jul" \
       --sow-rain-trigger 25 --fertilise-at-sowing 50
   ```

2. **JSON structure**: The .apsimx file is a tree of typed nodes:
   ```
   Simulations (root)
   ├── DataStore (output database)
   └── Simulation
       ├── Clock (start/end dates)
       ├── Summary (logging)
       ├── Weather (→ .met file)
       ├── MicroClimate
       └── Zone ("Field", area=1 ha)
           ├── Soil (from soil.json)
           ├── Plant (crop + cultivar)
           ├── SurfaceOrganicMatter
           ├── SowingRule (Manager)
           ├── HarvestRule (Manager)
           ├── Fertiliser (optional)
           └── Report (output variables)
   ```

3. **Key parameters set during assembly**:
   - Clock.Start / Clock.End
   - Weather.FileName (uses %root% for relative paths)
   - Zone.Area (default 1.0 ha)
   - Plant population, cultivar, row spacing, sowing depth
   - Report.VariableNames (which outputs to track)

4. **Report variable selection**: Default variables include:
   - `[Clock].Today` — simulation date
   - `[Crop].Grain.Wt` — grain yield (g/m²)
   - `[Crop].AboveGround.Wt` — total above-ground biomass (g/m²)
   - `[Crop].Leaf.LAI` — leaf area index (m²/m²)
   - `[Crop].Phenology.Stage` — development stage
   - `[Soil].Water.ESW` — extractable soil water (mm)
   - Weather variables (Rain, MaxT, MinT, Radn)

## Verification

- [ ] .apsimx is valid JSON (parseable)
- [ ] Root node has `$type: "Models.Core.Simulations, Models"`
- [ ] Version field is present (≥200)
- [ ] DataStore node exists
- [ ] Weather.FileName path resolves to an existing .met file
- [ ] Soil node contains Physical, WaterBalance children
- [ ] Plant node has correct ResourceName matching crop
- [ ] Clock dates are set correctly
- [ ] At least one Report with VariableNames

## Traps

- **%root% path not resolving** (dt_004): The %root% macro is replaced at
  runtime with the directory containing the .apsimx file. If you move the
  .apsimx without moving the .met, the path breaks.

- **Population in plants/ha instead of plants/m²** (dt_005): The tool
  validates that population < 1000. If you specify 100000 (meaning plants/ha),
  divide by 10000 first.

- **Missing $type fields**: Every node needs a $type with the full
  assembly-qualified name. Missing $type causes deserialization failure.

- **Wrong cultivar name** (dt_010): The cultivar must match exactly what's
  available in APSIM's resource files. Case-sensitive.

- **Version mismatch**: The Version field must match what the installed APSIM
  expects. Older files are auto-upgraded, but future versions may not be
  backward-compatible.

## Example

```bash
python build_apsimx.py --output dalby_wheat.apsimx \
    --met-file dalby.met --soil-json dalby_soil.json \
    --crop Wheat --cultivar Hartog --population 100 \
    --start 1992-01-01 --end 1995-12-31 \
    --sowing-date 1992-05-20 --row-spacing 250 --sowing-depth 30

# Output:
# {
#   "status": "ok",
#   "crop": "Wheat",
#   "cultivar": "Hartog",
#   "period": "1992-01-01 to 1995-12-31",
#   "met_path": "%root%/dalby.met",
#   "warnings": []
# }
```
