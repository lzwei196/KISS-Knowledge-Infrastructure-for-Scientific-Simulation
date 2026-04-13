# Stage 0–1: WSIMOD Configuration & Domain Setup

## Purpose

Configure the WSIMOD simulation: define the study period, select pollutants to track,
design the node-arc graph topology, and choose execution mode (CLI vs Python API).
This stage produces the structural blueprint that all downstream stages depend on.

## Inputs

| Input               | Format   | Source                    | Notes                          |
|---------------------|----------|---------------------------|--------------------------------|
| Study period        | Dates    | User specification        | Daily timestep series          |
| Pollutant list      | List     | `constants.POLLUTANTS`    | Default: 12 pollutants         |
| Node graph          | Dict     | Domain knowledge          | Node types + connectivity      |
| Execution mode      | String   | User choice               | `cli` or `api`                 |

## Outputs

| Output              | Format   | Destination               | Notes                          |
|---------------------|----------|---------------------------|--------------------------------|
| YAML settings       | `.yaml`  | `config.yaml`             | Full model definition          |
| Date series         | List     | `settings["dates"]`       | Pandas-compatible dates        |
| Node list           | List     | `settings["nodes"]`       | List of node config dicts      |
| Arc list            | List     | `settings["arcs"]`        | List of arc config dicts       |

## Procedure

1. **Define simulation dates**: Create a pandas date_range at daily frequency.
   ```python
   import pandas as pd
   dates = pd.date_range("2009-01-01", "2009-12-31", freq="D")
   ```

2. **Choose pollutants**: Use default (12 pollutants) or simplified (phosphate + temperature).
   ```python
   from wsimod.core.constants import set_simple_pollutants
   set_simple_pollutants()  # Only phosphate + temperature
   ```

3. **Design node graph**: Identify physical components and their connections.
   Every graph needs at least one `Waste` node as the terminal outlet.

4. **Define nodes as dictionaries**: Each node dict must have `type_` and `name`.
   ```python
   nodes = [
       {"type_": "Land", "name": "my_land", "surfaces": [...], "data_input_dict": {...}},
       {"type_": "Sewer", "name": "my_sewer", "capacity": 0.04},
       {"type_": "Waste", "name": "outlet"},
   ]
   ```

5. **Define arcs**: Each arc needs `type_`, `name`, `in_port`, `out_port`.
   The `in_port` and `out_port` must match node names exactly (case-sensitive).

6. **Choose execution mode**:
   - CLI: `wsimod config.yaml --inputs ./data --outputs ./results`
   - API: `model = Model(); model.dates = dates; model.add_nodes(nodes); model.run()`

## Verification

- [ ] All node names are unique
- [ ] All arc `in_port`/`out_port` reference existing node names
- [ ] At least one `Waste` node exists (terminal outlet)
- [ ] Date series has no duplicates and is daily frequency
- [ ] If using CLI: YAML file parses without error

## Traps

| Trap   | Symptom                          | Fix                                     |
|--------|----------------------------------|-----------------------------------------|
| dt_005 | KeyError at model construction   | Arc port names must match node names     |
| dt_004 | Zero forcing, no error           | data_input_dict keys must be tuples      |
| dt_014 | Different results on rerun       | Orchestration order matters; don't change |

## Example

```python
from wsimod.orchestration.model import Model
import pandas as pd

model = Model()
model.dates = pd.date_range("2009-01-01", "2009-12-31", freq="D")
model.add_nodes([
    {"type_": "Land", "name": "land", "data_input_dict": land_inputs,
     "surfaces": [{"type_": "PerviousSurface", "surface": "rural",
                    "area": 100, "depth": 0.5}]},
    {"type_": "Node", "name": "river"},
    {"type_": "Waste", "name": "outlet"},
])
model.add_arcs([
    {"type_": "Arc", "name": "runoff", "in_port": "land", "out_port": "river"},
    {"type_": "Arc", "name": "outflow", "in_port": "river", "out_port": "outlet"},
])
```
