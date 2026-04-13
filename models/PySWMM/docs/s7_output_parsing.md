# s7 — Output Parsing

## Purpose

Extract timeseries data from the SWMM binary output file (.out) and convert
to human-readable CSV format for analysis, visualization, and comparison
with observations. Also parse the text report file (.rpt) for mass balance
summaries and peak values.

## Inputs

| Input              | Source               | Format                    |
|--------------------|----------------------|---------------------------|
| Binary output      | Stage s6 run         | .out binary file          |
| Report file        | Stage s6 run         | .rpt text file            |
| Element IDs        | Model .inp file      | Node/link/subcatch names  |

## Outputs

| Output             | File                 | Format                    |
|--------------------|----------------------|---------------------------|
| Node timeseries    | node_{id}.csv        | CSV: time, depth, flow... |
| Link timeseries    | link_{id}.csv        | CSV: time, flow, depth... |
| Subcatch timeseries| subcatch_{id}.csv    | CSV: time, rain, runoff...|
| System timeseries  | system.csv           | CSV: time, rain, outflow  |
| Summary statistics | summary.json         | JSON                      |

## Procedure

### Method 1: PySWMM Output API (Recommended)

```python
from pyswmm import Output, NodeSeries, LinkSeries, SubcatchSeries, SystemSeries

with Output('model.out') as out:
    # Metadata
    print(f"Period: {out.start} to {out.end}")
    print(f"Timesteps: {len(out.times)}")
    print(f"Nodes: {list(out.nodes.keys())}")
    print(f"Links: {list(out.links.keys())}")
    print(f"Subcatchments: {list(out.subcatchments.keys())}")

    # Node timeseries
    ns = NodeSeries(out)['J1']
    depth = ns.invert_depth       # dict: {datetime: float}
    inflow = ns.total_inflow
    flooding = ns.overflow

    # Link timeseries
    ls = LinkSeries(out)['C1']
    flow = ls.flow_rate
    velocity = ls.flow_velocity

    # Subcatchment timeseries
    ss = SubcatchSeries(out)['S1']
    rainfall = ss.rainfall
    runoff = ss.runoff_rate
    infiltration = ss.infiltration_loss

    # System-wide timeseries
    sys = SystemSeries(out)
    total_rain = sys.rainfall
    total_outflow = sys.outflow
```

### Method 2: During Simulation (Real-Time Collection)

```python
from pyswmm import Simulation, Nodes, Links
import csv

with Simulation('model.inp') as sim:
    j1 = Nodes(sim)['J1']
    c1 = Links(sim)['C1']

    with open('results.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['time', 'j1_depth', 'c1_flow'])
        for step in sim:
            writer.writerow([sim.current_time, j1.depth, c1.flow])
```

### Available Output Variables

**Node attributes:**
| Attribute      | Property           | Units (US)  | Units (SI)  |
|----------------|-------------------|-------------|-------------|
| Depth          | `invert_depth`    | ft          | m           |
| Total inflow   | `total_inflow`    | CFS         | CMS         |
| Outflow        | `outflow`         | CFS         | CMS         |
| Flooding       | `overflow`        | CFS         | CMS         |
| Volume         | `volume`          | ft³         | m³          |
| Lateral inflow | `lateral_inflow`  | CFS         | CMS         |

**Link attributes:**
| Attribute      | Property           | Units (US)  | Units (SI)  |
|----------------|-------------------|-------------|-------------|
| Flow rate      | `flow_rate`       | CFS         | CMS         |
| Depth          | `flow_depth`      | ft          | m           |
| Velocity       | `flow_velocity`   | ft/s        | m/s         |
| Volume         | `flow_volume`     | ft³         | m³          |
| Froude number  | `froude_number`   | —           | —           |
| Setting        | `setting`         | 0–1         | 0–1         |

**Subcatchment attributes:**
| Attribute      | Property            | Units (US) | Units (SI)  |
|----------------|---------------------|------------|-------------|
| Rainfall       | `rainfall`          | in/hr      | mm/hr       |
| Runoff         | `runoff_rate`       | CFS        | CMS         |
| Infiltration   | `infiltration_loss` | in/hr      | mm/hr       |
| Evaporation    | `evap_loss`         | in/day     | mm/day      |
| Snow depth     | `snow_depth`        | in         | mm          |

## Verification

- [ ] Output file is not empty (size > 0)
- [ ] Number of timesteps matches expected count
- [ ] All requested element IDs found in output
- [ ] No NaN or Inf values in extracted timeseries
- [ ] Flow values are physically plausible (Q_peak < rational method estimate)
- [ ] Mass balance: total inflow ≈ total outflow + storage change + losses

## Traps

| Trap ID | Description                                          | Severity |
|---------|------------------------------------------------------|----------|
| DT-015  | Element ID not in output → silently returns empty    | HIGH     |
| DT-016  | Output units depend on FLOW_UNITS in [OPTIONS]       | HIGH     |
| DT-017  | .out file truncated if simulation crashed mid-run    | MEDIUM   |
| DT-018  | Reporting timestep ≠ routing timestep → interpolation| LOW      |

## Example

```bash
# Extract all nodes, links, and system data
python ki/tools/parse_swmm_output.py \
    --input model.out \
    --output-dir ./results/ \
    --all

# Extract specific elements
python ki/tools/parse_swmm_output.py \
    --input model.out \
    --output-dir ./results/ \
    --nodes J1,J2,Outfall \
    --links C1,W1 \
    --subcatchments S1,S2 \
    --system
```

## Computing Performance Metrics

```python
import numpy as np

def nash_sutcliffe(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    return 1 - np.sum((obs - sim)**2) / np.sum((obs - np.mean(obs))**2)

def kge(obs, sim):
    """Kling-Gupta Efficiency."""
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    return 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

def pbias(obs, sim):
    """Percent Bias."""
    return 100 * np.sum(sim - obs) / np.sum(obs)
```
