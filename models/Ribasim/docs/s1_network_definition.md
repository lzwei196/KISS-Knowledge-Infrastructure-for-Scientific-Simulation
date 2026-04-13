# Stage 1: Network Definition

## Purpose

Build the water system network topology — nodes (water bodies, structures,
boundaries) and links (flow connections, control links). This stage populates
the `Node` and `Link` tables in the GeoPackage database.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| Node locations | CSV/shapefile with coordinates | User/GIS | Yes |
| Node types | Classification per node | User | Yes |
| Link definitions | From-to node pairs | User | Yes |
| Link types | "flow", "control", etc. | User | Yes |

## Outputs

| Output | Format | Path |
|--------|--------|------|
| GeoPackage with Node table | GPKG | `input/database.gpkg` → `Node` layer |
| GeoPackage with Link table | GPKG | `input/database.gpkg` → `Link` layer |

## Procedure

### Step 1: Define nodes

Each node needs:
- **node_id**: Unique integer identifier (Int32)
- **node_type**: One of 16 valid types (Basin, Pump, Outlet, etc.)
- **geometry**: Point coordinates in the model CRS
- **name** (optional): Human-readable label
- **subnetwork_id** (optional): For allocation (0 = not in allocation)

```python
import ribasim
from ribasim import Model, Node
from shapely.geometry import Point

model = Model(starttime="2020-01-01", endtime="2021-01-01", crs="EPSG:28992")

# Add nodes
model.basin.add(Node(1, Point(0, 0), name="Lake"))
model.pump.add(Node(2, Point(100, 0), name="Pump_A"))
model.terminal.add(Node(3, Point(200, 0), name="Outfall"))
```

### Step 2: Define links

Links connect nodes and define water flow paths:
- **link_type = "flow"**: Water flows between nodes
- **link_type = "control"**: Information link from control node to controlled node
- **link_type = "listen"**: Auto-created from observed to control node

```python
model.link.add(model.basin[1], model.pump[2], link_type="flow")
model.link.add(model.pump[2], model.terminal[3], link_type="flow")
```

### Step 3: Validate connectivity

Ribasim enforces strict connectivity rules:

| From Node | Allowed To Nodes |
|-----------|-----------------|
| Basin | LinearResistance, TabulatedRatingCurve, ManningResistance, Pump, Outlet, UserDemand, Junction |
| FlowBoundary | Basin, Junction |
| LevelBoundary | LinearResistance, Pump, Outlet, TabulatedRatingCurve |
| Pump | Basin, Junction, Terminal |
| Outlet | Basin, Junction, Terminal |
| TabulatedRatingCurve | Basin, Junction, Terminal |
| Junction | Basin, Junction, LinearResistance, TabulatedRatingCurve, ManningResistance, Pump, Outlet, UserDemand, Terminal |
| UserDemand | Basin, Junction, Terminal |

Control nodes (DiscreteControl, ContinuousControl, PidControl) connect via
"control" links to the nodes they modify.

### Step 4: Write to GeoPackage

```python
model.write("model_dir/ribasim.toml")
# This creates input/database.gpkg with Node and Link tables
```

## Verification

1. Check all node_ids are unique
2. Check all node_types are valid Ribasim types
3. Check all link from/to references exist in Node table
4. Verify connectivity rules (Basin cannot connect directly to Basin)
5. Check network is connected (no orphan nodes)
6. Verify at least one Basin node exists

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Direct Basin-to-Basin | Fatal | Basins cannot connect directly — need a structure node (Pump, Outlet, LinearResistance, etc.) between them. |
| Orphan nodes | Warning | Nodes with no links are silently ignored. They don't cause errors but waste resources. |
| Duplicate node_ids | Fatal | Each node_id must be unique across ALL node types. |
| Missing Terminal | Silent | If water has no exit path, basins will overflow or the solver may fail. Always add Terminal nodes at model boundaries. |
| Wrong link_type | Silent | Using "flow" instead of "control" for control links means the control node is treated as a flow node, causing unexpected behavior. |

## Example

```python
import ribasim
from ribasim import Model, Node
from shapely.geometry import Point

model = Model(
    starttime="2020-01-01",
    endtime="2021-01-01",
    crs="EPSG:28992",
)

# Reservoir with inflow and regulated outflow
model.flow_boundary.add(
    Node(1, Point(0, 100)),
    [ribasim.FlowBoundary.Static(flow_rate=[5.0])],
)
model.basin.add(
    Node(2, Point(100, 100)),
    [
        ribasim.Basin.Profile(area=[100, 5000, 20000], level=[0, 5, 10]),
        ribasim.Basin.State(level=[5.0]),
    ],
)
model.outlet.add(
    Node(3, Point(200, 100)),
    [ribasim.Outlet.Static(flow_rate=[3.0], min_upstream_level=[2.0])],
)
model.terminal.add(Node(4, Point(300, 100)))

model.link.add(model.flow_boundary[1], model.basin[2])
model.link.add(model.basin[2], model.outlet[3])
model.link.add(model.outlet[3], model.terminal[4])

model.write("example/ribasim.toml")
```
