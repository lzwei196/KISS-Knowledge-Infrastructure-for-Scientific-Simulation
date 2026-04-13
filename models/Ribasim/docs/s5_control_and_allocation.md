# Stage 5: Control Rules and Water Allocation

## Purpose

Configure rule-based control of hydraulic structures (pumps, outlets, weirs)
and set up priority-based water allocation across demand nodes. This stage
enables realistic operational management of water infrastructure.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| Control rules | Condition-logic tables | Operations manual | For controlled structures |
| PID parameters | Gains and targets | Calibration | For PID-controlled structures |
| Demand priorities | Integer rankings | Water rights / policy | For allocation |
| Subnetwork definitions | Node assignments | Network design | For allocation |

## Outputs

| Output | Format | Path |
|--------|--------|------|
| DiscreteControl tables | GeoPackage | `input/database.gpkg` |
| PidControl tables | GeoPackage | `input/database.gpkg` |
| ContinuousControl tables | GeoPackage | `input/database.gpkg` |
| Allocation configuration | TOML section | `ribasim.toml` |

## Procedure

### Step 1: Discrete Control (if-then rules)

DiscreteControl implements a state machine: when conditions on observed
variables cross thresholds, the controlled node's parameters switch.

**Components**:
1. **Variable**: What to observe (basin level, flow, etc.)
2. **Condition**: Threshold with hysteresis (threshold_high for rising, threshold_low for falling)
3. **Logic**: Maps truth states to control states

```python
# Example: Pump turns on when basin level > 5m, off when < 4m
model.discrete_control.add(
    Node(10, Point(50, 50)),
    [
        ribasim.DiscreteControl.Variable(
            compound_variable_id=1,
            listen_node_id=[2],       # Basin to observe
            variable=["level"],
        ),
        ribasim.DiscreteControl.Condition(
            compound_variable_id=[1],
            threshold_high=[5.0],     # Turn on above 5m
            threshold_low=[4.0],      # Turn off below 4m (hysteresis)
        ),
        ribasim.DiscreteControl.Logic(
            truth_state=["F", "T"],   # F=below threshold, T=above
            control_state=["off", "on"],
        ),
    ],
)

# Connect control to pump
model.link.add(model.discrete_control[10], model.pump[3], link_type="control")

# Define pump states
model.pump.add(
    Node(3, Point(100, 50)),
    [ribasim.Pump.Static(
        flow_rate=[0.0, 5.0],        # off=0, on=5 m³/s
        control_state=["off", "on"],
    )],
)
```

### Step 2: PID Control (continuous feedback)

PidControl adjusts Pump/Outlet flow to maintain a target basin level:

```
Q = Kp × e + Ki × ∫e dt + Kd × de/dt
where e = target_level - current_level
```

```python
model.pid_control.add(
    Node(20, Point(50, 50)),
    [ribasim.PidControl.Static(
        listen_node_id=[2],           # Basin to control
        target=[5.0],                 # Target level (m)
        proportional=[-1e-3],         # Kp (s⁻¹) — NEGATIVE for level regulation
        integral=[-1e-7],             # Ki (s⁻²) — NEGATIVE
        derivative=[0.0],             # Kd (dimensionless)
    )],
)
model.link.add(model.pid_control[20], model.outlet[3], link_type="control")
```

**TRAP**: PID gains must be **negative** when the controlled structure increases
outflow to lower the basin level. Positive gains cause runaway oscillation.

### Step 3: Water Allocation Setup

Allocation distributes available water among competing demands using linear
programming (HiGHS solver).

**Step 3a: Assign subnetwork IDs**

```python
# Nodes in allocation network get subnetwork_id > 0
model.basin.add(Node(1, Point(0, 0), subnetwork_id=1), [...])
model.user_demand.add(Node(5, Point(200, 0), subnetwork_id=1), [...])
```

**Step 3b: Define demands with priorities**

Lower priority number = higher priority (served first):

```python
model.user_demand.add(
    Node(5, Point(200, 0), subnetwork_id=1),
    [ribasim.UserDemand.Time(
        time=["2020-01-01", "2020-07-01"],
        demand=[10.0, 20.0],           # m³/s
        return_factor=[0.3, 0.3],      # 30% returned to system
        min_level=[1.0, 1.0],          # Stop extraction below 1m
        demand_priority=[1, 1],        # Highest priority
    )],
)
```

**Step 3c: Configure allocation timestep**

```toml
[allocation]
timestep = 86400    # Seconds! Not days!
```

### Step 4: Continuous Control

ContinuousControl maps a continuous variable to a parameter via a lookup function:

```python
model.continuous_control.add(
    Node(30, Point(50, 50)),
    [
        ribasim.ContinuousControl.Variable(
            listen_node_id=[2],
            variable=["level"],
        ),
        ribasim.ContinuousControl.Function(
            input=[0.0, 3.0, 5.0, 10.0],   # Observed levels
            output=[0.0, 0.0, 2.0, 10.0],  # Resulting flow rates
        ),
    ],
)
```

## Verification

1. All control nodes have "control" link_type connections
2. PID gains have correct sign (usually negative for level control)
3. Discrete control truth_state strings match number of conditions
4. Allocation subnetwork_id is consistent within connected components
5. Demand priorities are positive integers
6. Return factors are in [0, 1] range

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| PID sign error | **SILENT** | Positive gains with outflow control causes level to increase instead of decrease — runaway feedback. |
| Missing control link | **SILENT** | Control node without "control" link to target has no effect. No error raised. |
| Allocation timestep units | **SILENT** | In seconds, not days. `timestep = 1` means every second (very slow simulation). |
| Hysteresis gap too small | Degraded | If threshold_high ≈ threshold_low, control chatters between states at every timestep. |
| subnetwork_id = 0 | **SILENT** | Nodes with subnetwork_id=0 are excluded from allocation. Demands at these nodes are never served. |
| return_factor > 1 | **SILENT** | Creates water from nothing. Must be in [0, 1]. |

## Example

```python
# Complete discrete control example: flood gate
# Gate opens when upstream basin > 8m, closes when < 6m

model.discrete_control.add(
    Node(100, Point(150, 0), name="FloodGate_Control"),
    [
        ribasim.DiscreteControl.Variable(
            compound_variable_id=1,
            listen_node_id=[1],        # Upstream basin
            variable=["level"],
        ),
        ribasim.DiscreteControl.Condition(
            compound_variable_id=[1],
            threshold_high=[8.0],      # Open at 8m
            threshold_low=[6.0],       # Close at 6m
        ),
        ribasim.DiscreteControl.Logic(
            truth_state=["F", "T"],
            control_state=["closed", "open"],
        ),
    ],
)

model.outlet.add(
    Node(50, Point(200, 0), name="FloodGate"),
    [ribasim.Outlet.Static(
        flow_rate=[0.0, 50.0],         # closed=0, open=50 m³/s
        control_state=["closed", "open"],
    )],
)

model.link.add(model.discrete_control[100], model.outlet[50], link_type="control")
```
