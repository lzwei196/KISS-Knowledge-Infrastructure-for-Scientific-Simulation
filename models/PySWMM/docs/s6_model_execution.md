# s6 — Model Execution

## Purpose

Run the EPA SWMM5 simulation via PySWMM, with preflight validation,
optional real-time control, progress monitoring, and post-run mass
balance verification.

## Inputs

| Input              | Source               | Format                    |
|--------------------|----------------------|---------------------------|
| SWMM input file    | Stages s0–s5         | .inp text file            |
| Hotstart file      | Previous run (opt)   | .hsf binary (optional)    |
| Control logic      | Python callbacks     | Python functions          |

## Outputs

| Output             | File           | Format                    |
|--------------------|----------------|---------------------------|
| Report file        | model.rpt      | Text summary              |
| Binary output      | model.out      | SWMM binary timeseries    |
| Hotstart save      | model.hsf      | Binary state (optional)   |
| Collected data     | results.csv    | CSV (if using collection) |

## Procedure

### Method 1: Full Execution (Fastest)

```python
from pyswmm import Simulation

with Simulation('model.inp') as sim:
    sim.execute()

print(f"Runoff error:  {sim.runoff_error:.2f}%")
print(f"Routing error: {sim.flow_routing_error:.2f}%")
```

### Method 2: Stepped Execution with Data Collection

```python
from pyswmm import Simulation, Nodes, Links

with Simulation('model.inp') as sim:
    j1 = Nodes(sim)['J1']
    outfall = Nodes(sim)['Outfall']
    conduit = Links(sim)['C1']

    results = []
    for step in sim:
        results.append({
            'time': sim.current_time,
            'j1_depth': j1.depth,
            'outfall_flow': outfall.total_inflow,
            'conduit_flow': conduit.flow,
        })
```

### Method 3: Real-Time Control

```python
from pyswmm import Simulation, Nodes, Links

with Simulation('model.inp') as sim:
    j1 = Nodes(sim)['J1']
    pump = Links(sim)['P1']

    def control_pump():
        if j1.depth > 3.0:
            pump.target_setting = 1.0   # Turn on
        elif j1.depth < 1.0:
            pump.target_setting = 0.0   # Turn off

    sim.add_before_step(control_pump)

    for step in sim:
        pass  # Control logic fires via callback
```

### Method 4: Using Hotstart Files

```python
from pyswmm import Simulation

# Run warmup and save state
with Simulation('model.inp') as sim:
    sim.save_hotstart('warmup.hsf')
    sim.execute()

# Resume from saved state
with Simulation('model.inp') as sim:
    sim.use_hotstart('warmup.hsf')
    for step in sim:
        pass
```

### Method 5: SimulationPreConfig (Modify INP Before Running)

```python
from pyswmm import Simulation, SimulationPreConfig

config = SimulationPreConfig()
config.add_update_by_token("SUBCATCHMENTS", "S1", 2, "J2")  # Change outlet
config.add_update_by_token("CONDUITS", "C1", 4, "0.015")    # Change Manning's n

with Simulation('model.inp', sim_preconfig=config) as sim:
    sim.execute()
```

## Verification

- [ ] Runoff continuity error < 5% (ideally < 1%)
- [ ] Flow routing error < 5% (ideally < 1%)
- [ ] Quality routing error < 5% (if WQ enabled)
- [ ] Output file (.out) size > 0 bytes
- [ ] Report file (.rpt) exists and contains results
- [ ] No "ERROR" lines in report file
- [ ] Peak flows are physically plausible for catchment size

## Traps

| Trap ID | Description                                          | Severity |
|---------|------------------------------------------------------|----------|
| DT-010  | MultiSimulationError from nested Simulation objects  | CRITICAL |
| DT-011  | Large routing error from DYNWAVE with big timestep   | HIGH     |
| DT-012  | Missing `with` statement → resources not released    | HIGH     |
| DT-013  | step_advance(0) → infinite loop                      | HIGH     |
| DT-014  | Callbacks modifying node.depth directly (read-only)  | MEDIUM   |

## Performance Tips

- Use `sim.execute()` if no intervention needed (10–100x faster than stepping)
- Use `sim.step_advance(300)` to check every 5 min instead of every routing step
- DYNWAVE routing is 5–20x slower than KINWAVE
- Set `THREADS > 1` in [OPTIONS] for DYNWAVE on multi-core systems

## Example Tool Usage

```bash
python ki/tools/run_pyswmm.py \
    --input model.inp \
    --report model.rpt \
    --output model.out \
    --collect-nodes J1,J2,Outfall \
    --collect-links C1,C2 \
    --results-csv results.csv
```
