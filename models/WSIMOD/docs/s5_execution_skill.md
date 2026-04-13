# Stage 5: Model Execution

## Purpose

Run the WSIMOD simulation either through the CLI entry point or the Python API.
Understand the orchestration sequence, handle runtime errors, and capture output.

## Inputs

| Input                 | Format   | Source              | Notes                           |
|-----------------------|----------|---------------------|---------------------------------|
| Settings YAML         | `.yaml`  | Stage 0 output      | CLI mode                        |
| Model object          | Python   | Stage 0-4 setup     | API mode                        |
| Input data directory  | Path     | Stage 2-3 output    | CSV/parquet files               |
| Output directory      | Path     | User specification   | Will contain flows/tanks/surfaces|

## Outputs

| Output              | Format   | Destination               | Notes                          |
|---------------------|----------|---------------------------|--------------------------------|
| flows               | CSV      | `outputs/flows.csv`       | Arc flow + pollutant data      |
| tanks               | CSV      | `outputs/tanks.csv`       | Storage node states            |
| surfaces            | CSV      | `outputs/surfaces.csv`    | Land surface states            |

## Procedure

### CLI Mode
```bash
wsimod config.yaml --inputs ./data --outputs ./results
```

The CLI entry point (`wsimod.__main__.run`):
1. Parses YAML settings
2. Detects if "saved" model or "custom" settings
3. For custom: loads data files, applies scaling/filters, builds model
4. For saved: loads pickled model from directory
5. Calls `model.run()` and saves CSV outputs

### API Mode
```python
from wsimod.orchestration.model import Model

model = Model()
model.dates = dates
model.add_nodes(node_list)
model.add_arcs(arc_list)

# Run simulation
flows, tanks, _, surfaces = model.run()

# Save outputs
import pandas as pd
pd.DataFrame(flows).to_csv("flows.csv")
pd.DataFrame(tanks).to_csv("tanks.csv")
pd.DataFrame(surfaces).to_csv("surfaces.csv")
```

### Orchestration Sequence

Each timestep, WSIMOD calls node functions in this order:
1. FWTW → treat_water
2. Demand → create_demand
3. Land → run
4. Groundwater → infiltrate
5. Sewer → make_discharge
6. Foul → make_discharge
7. WWTW → calculate_discharge
8. Groundwater → distribute
9. River → calculate_discharge
10. Reservoir → make_abstractions
11. Land → apply_irrigation
12. WWTW → make_discharge
13. Catchment → route

Only node types present in the model are called. The order is defined in
`Model.__init__()` and can be customized via `model.orchestration`.

### Mass Balance Checking

After each timestep, every node checks:
```
sum(mass_balance_in) ≈ sum(mass_balance_out) + sum(mass_balance_ds)
```
Tolerance: `FLOAT_ACCURACY = 1e-11`. Violations raise warnings.

## Verification

- [ ] Model completes without exceptions
- [ ] flows.csv, tanks.csv, surfaces.csv are non-empty
- [ ] No mass balance warnings in output
- [ ] Flow values are physically reasonable (not 0, not 1e10)
- [ ] Runtime is reasonable (~1 sec per 100 timesteps for simple models)

## Traps

| Trap   | Symptom                               | Fix                                       |
|--------|---------------------------------------|-------------------------------------------|
| dt_013 | KeyError during run()                 | data_input_dict missing dates/variables   |
| dt_005 | KeyError at add_arcs()                | Arc port name doesn't match any node      |
| dt_014 | Results change when reordering nodes  | Orchestration order is deterministic       |
| dt_016 | ImportError at startup                | Missing dependency (PyYAML, pandas, etc.) |
| dt_009 | Mass balance violations ignored       | Errors below 1e-11 are masked             |

## Example

```python
# Full execution with timing
import time
from wsimod.orchestration.model import Model

model = Model()
model.dates = dates
model.add_nodes(nodes)
model.add_arcs(arcs)

start = time.time()
flows, tanks, _, surfaces = model.run()
elapsed = time.time() - start

print(f"Completed in {elapsed:.1f}s")
print(f"Flow records: {len(flows)}")
print(f"Tank records: {len(tanks)}")
print(f"Surface records: {len(surfaces)}")
```
