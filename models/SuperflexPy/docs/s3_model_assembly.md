# S3: Model Assembly

## Purpose

Build a SuperflexPy model by composing Elements into Units, Units into Nodes, and
Nodes into Networks. This stage defines the hydrological model structure — the
arrangement of reservoirs, lag functions, splitters, and junctions that represent
the rainfall-runoff process.

## Inputs

| Input | Description | Format |
|-------|-------------|--------|
| Model structure | Choice of elements and connections | Python code |
| Numerical solver | ODE approximation method | Solver object |
| Root finder | For implicit solvers | Root finder object |
| Parameters | Initial parameter values | dict |
| Initial states | S0, lag arrays | dict |

## Outputs

| Output | Description | Type |
|--------|-------------|------|
| Model object | Configured Unit/Node/Network | SuperflexPy object |
| Parameter names | Full prefixed names | list of strings |
| State names | Full prefixed state names | list of strings |

## Procedure

### Step 1: Choose and configure the numerical solver

```python
from superflexpy.implementation.root_finders.pegasus import PegasusPython
from superflexpy.implementation.numerical_approximators.implicit_euler import ImplicitEulerPython

root_finder = PegasusPython()
num_app = ImplicitEulerPython(root_finder=root_finder)
```

### Step 2: Create Elements

```python
from superflexpy.implementation.elements.hbv import UnsaturatedReservoir, PowerReservoir

ur = UnsaturatedReservoir(
    parameters={'Smax': 200.0, 'Ce': 1.0, 'm': 0.01, 'beta': 2.0},
    states={'S0': 10.0},
    approximation=num_app,
    id='ur'
)

fr = PowerReservoir(
    parameters={'k': 0.05, 'alpha': 2.5},
    states={'S0': 0.0},
    approximation=num_app,
    id='fr'
)
```

### Step 3: Compose into a Unit

```python
from superflexpy.framework.unit import Unit

model = Unit(
    layers=[[ur], [fr]],
    id='hbv_simple'
)
```

### Step 4 (optional): Create Node with multiple HRUs

```python
from superflexpy.framework.node import Node

node = Node(
    units=[unit_forest, unit_grassland],
    weights=[0.6, 0.4],
    area=150.0,  # km²
    id='subcatchment_1'
)
```

### Step 5 (optional): Create Network

```python
from superflexpy.framework.network import Network

network = Network(
    nodes=[node_headwater, node_middle, node_outlet],
    topology={'node_headwater': 'node_middle',
              'node_middle': 'node_outlet',
              'node_outlet': None},
    id='catchment'
)
```

## Verification

- [ ] `model.get_parameters_name()` returns all expected parameters
- [ ] `model.get_states_name()` returns all expected states
- [ ] Layer structure matches intended DAG (no orphaned elements)
- [ ] Splitter weight/direction dimensions match element counts
- [ ] Junction direction matrix is correct
- [ ] Network topology has no cycles

## Traps

| Trap ID | Description | Impact |
|---------|-------------|--------|
| dt_007 | Lag state set to array instead of None | Crash or wrong UH |
| dt_008 | Splitter matrix dimensions wrong | Cryptic IndexError |
| dt_011 | Network topology has a cycle | Infinite loop |
| dt_012 | Node weights don't sum to 1.0 | Silent scaling error |

## Example: Building GR4J from scratch

```python
from superflexpy.framework.unit import Unit
from superflexpy.implementation.elements.gr4j import *
from superflexpy.implementation.elements.structure_elements import *
from superflexpy.implementation.numerical_approximators.implicit_euler import ImplicitEulerPython
from superflexpy.implementation.root_finders.pegasus import PegasusPython

solver = PegasusPython()
num_app = ImplicitEulerPython(root_finder=solver)

gr4j = Unit(
    layers=[
        [InterceptionFilter(id='ir')],
        [ProductionStore(parameters={'x1': 350, 'alpha': 2.0, 'beta': 5.0, 'ni': 4/9},
                         states={'S0': 10.0}, approximation=num_app, id='ps')],
        [Splitter(weight=[[0.9], [0.1]], direction=[[0], [0]], id='spl')],
        [UnitHydrograph1(parameters={'lag-time': 1.7}, states={'lag': None}, id='uh1'),
         UnitHydrograph2(parameters={'lag-time': 3.4}, states={'lag': None}, id='uh2')],
        [RoutingStore(parameters={'x2': 0.0, 'x3': 90.0, 'gamma': 5.0, 'omega': 3.5},
                      states={'S0': 10.0}, approximation=num_app, id='rs'),
         Transparent(id='tr')],
        [Junction(direction=[[0, None], [1, None], [None, 0]], id='jun')],
        [FluxAggregator(id='fa')],
    ],
    id='gr4j'
)
```
