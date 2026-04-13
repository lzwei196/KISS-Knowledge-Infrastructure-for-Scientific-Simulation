# S3: Model Configuration

## Purpose

Build a complete HydroCNHS model YAML configuration file that defines the
water system structure, subbasin properties, routing network, and optional
ABM agents. This YAML file is the single input to `hydrocnhs.Model()`.

## Inputs

| Input | Format | Unit | Source |
|-------|--------|------|--------|
| Subbasin outlets | list of names | — | Basin delineation |
| Subbasin areas | list of floats | **ha** | GIS |
| Subbasin latitudes | list of floats | **decimal degrees** | GIS |
| Flow lengths | list of floats | **m** | GIS (along flow path) |
| Routing network | connectivity | — | Basin topology |
| Start/end dates | string | YYYY/M/D | User-defined |
| Parameters | dict | mixed | S2 output or calibrated |
| ABM specs (optional) | Python module | — | User-defined |

## Outputs

| Output | Format | Destination |
|--------|--------|-------------|
| model.yaml | YAML file | `hydrocnhs.Model(model="model.yaml")` |

## Procedure

### Method A: Using ModelBuilder (recommended)

```python
import hydrocnhs

mb = hydrocnhs.ModelBuilder(working_directory="/path/to/wd")

# 1. Define water system dates
mb.set_water_system(start_date="1981/1/1", end_date="2013/12/31")

# 2. Set rainfall-runoff model for all subbasins
mb.set_rainfall_runoff(
    outlet_list=["WSLO", "DLLO", "TRGC"],
    area_list=[47646.85, 3243.45, 6783.12],  # ha
    lat_list=[45.35, 45.40, 45.32],
    runoff_model="GWLF"                       # or "ABCD"
)

# 3. Define routing network
mb.set_routing_outlet(
    routing_outlet="WSLO",
    upstream_outlet_list=["DLLO", "TRGC"],
    flow_length_list=[80064.864, 52341.2]     # meters
)

# 4. (Optional) Add ABM agents
mb.add_agent(
    agt_type_class="Reservoir_AgtType",
    agt_name="ResAgt",
    api="DamAPI",
    link_dict={"HaggIn": -1, "ResAgt": 1}
)

# 5. Write YAML
mb.write_model_to_yaml(filename="model.yaml")
```

### Method B: Using build_model_config.py tool

```bash
python build_model_config.py \
    --start-date "1981/1/1" \
    --end-date "2013/12/31" \
    --outlets "WSLO,DLLO,TRGC" \
    --areas "47646.85,3243.45,6783.12" \
    --latitudes "45.35,45.40,45.32" \
    --runoff-model GWLF \
    --routing-outlet WSLO \
    --upstream-outlets "DLLO,TRGC" \
    --flow-lengths "80064.864,52341.2" \
    --output model.yaml
```

### Method C: Manual YAML editing

Edit an existing YAML file directly. The YAML has these top-level sections:
- `Path`: Working directory and modules path
- `WaterSystem`: Dates, outlets, model choices
- `RainfallRunoff`: Per-subbasin inputs and parameters
- `Routing`: Per-link routing parameters
- `ABM`: Agent definitions (optional)

## Verification

```python
import hydrocnhs

# Load and validate
model_dict = hydrocnhs.load_model("model.yaml")

# Check DataLength matches date range
from datetime import datetime
start = datetime.strptime(model_dict["WaterSystem"]["StartDate"], "%Y/%m/%d")
end = datetime.strptime(model_dict["WaterSystem"]["EndDate"], "%Y/%m/%d")
expected = (end - start).days + 1
actual = model_dict["WaterSystem"]["DataLength"]
assert expected == actual, f"DataLength mismatch: {actual} vs {expected}"

# Check all outlets have RainfallRunoff entries
for outlet in model_dict["WaterSystem"]["Outlets"]:
    assert outlet in model_dict["RainfallRunoff"], f"Missing RR config for {outlet}"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dt_008: Wrong date format | Silent parse failure | Use YYYY/M/D with slashes |
| dt_013: DataLength mismatch | Index error or silent truncation | Recompute from dates |
| dt_005: Area in km² | Discharge 100× too low | Convert to ha (×100) |
| dt_007: FlowLength in km | Routing delays wrong | Convert to m (×1000) |

## Example

A minimal 2-outlet GWLF configuration:

```yaml
Path:
  WD: /home/user/project
  Modules: ""
WaterSystem:
  StartDate: "1981/1/1"
  EndDate: "2013/12/31"
  DataLength: 12053
  NumSubbasins: 2
  Outlets: [WSLO, DLLO]
  NodeGroups: []
  RainfallRunoff: GWLF
  Routing: Lohmann
  ABM: {Modules: [], DamAPI: [], RiverDivAPI: [], ConveyingAPI: [],
        InsituAPI: [], DMClasses: [], Institutions: {}}
RainfallRunoff:
  WSLO:
    Inputs: {Area: 47646.85, Latitude: 45.35, S0: 2, U0: 10, SnowS: 5}
    Pars: {CN2: 72, IS: 0.1, Res: 0.1, Sep: 0.01, Alpha: 0.6,
           Beta: 0.5, Ur: 8.0, Df: 0.3, Kc: 1.0}
  DLLO:
    Inputs: {Area: 3243.45, Latitude: 45.40, S0: 2, U0: 10, SnowS: 5}
    Pars: {CN2: 65, IS: 0.15, Res: 0.08, Sep: 0.01, Alpha: 0.7,
           Beta: 0.5, Ur: 10.0, Df: 0.35, Kc: 1.1}
Routing:
  WSLO:
    DLLO:
      Inputs: {FlowLength: 80064.864, InstreamControl: false}
      Pars: {GShape: 50, GScale: 20, Velo: 30, Diff: 2000}
ABM: {}
```
