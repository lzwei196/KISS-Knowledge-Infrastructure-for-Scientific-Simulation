# Drainage Network Definition — Skill Document

> **Stage ID**: s2_drainage_network
> **Pipeline order**: 2 of 7
> **Depends on**: none (can run in parallel with S1 and S3)

## Purpose

The drainage network defines the conveyance system that transports stormwater from subcatchment outlets to the receiving water body. In SWMM, the network is a directed graph of nodes (junctions, outfalls, dividers, storage units) connected by links (conduits, pumps, orifices, weirs). The network carries the hydraulic routing computation — how water moves through pipes and channels over time.

Correct network definition is essential for accurate flood prediction. Errors in invert elevations, pipe sizes, connectivity, or cross-sections directly affect water levels, velocities, surcharging, and flooding. Unlike subcatchment parameters which affect runoff volume, network errors affect the timing, distribution, and severity of flooding.

This stage produces the nodes and links that subcatchments (S1) drain into, and that the hydraulic routing engine (S6) simulates.

## Prerequisites

Before starting this stage, verify:

- [ ] Drainage system layout is known (from municipal GIS, design drawings, or field survey)
- [ ] Pipe inventory data includes: material, diameter, length, invert elevations, manhole locations
- [ ] Outfall locations and boundary conditions are known (free outfall, river stage, tidal, fixed head)
- [ ] Decision on link offset convention: DEPTH (offset from node invert) or ELEVATION (absolute elevation)
- [ ] Datum is consistent: all elevations reference the same vertical datum (MSL, local benchmark, etc.)
- [ ] Python environment has: geopandas, networkx, numpy

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Junction data | config/file | Municipal GIS, survey, or design | Manhole locations, invert elevations, rim elevations |
| Conduit data | config/file | Pipe inventory, design drawings | Pipe segments with from/to nodes, diameter, material, length |
| Outfall data | config | Design, survey | Outfall locations, elevations, boundary types |
| Cross-section data | config | Design drawings, field survey | Pipe shapes, dimensions, custom transects |
| Coordinate system | string | Project specification | EPSG code for spatial reference |

## Procedure

Follow these steps in exact order.

### Step 1: Define Junction Nodes

Junctions represent manholes, inlet structures, and pipe connection points. Each junction needs:

| Parameter | Description | Units (CMS) | Typical Range |
|-----------|-------------|-------------|---------------|
| ID | Unique identifier | string | "J1", "MH_001" |
| Invert_Elev | Bottom elevation of the junction | meters | Varies by site |
| Max_Depth | Maximum water depth (invert to rim) | meters | 1.0 - 6.0 |
| Init_Depth | Initial water depth | meters | 0 (usually) |
| Surcharge_Depth | Additional depth for surcharging | meters | 0 |
| Aponded | Ponded area for surface flooding | m2 | 0-10000 |

```bash
python tools/s2_drainage_network/create_drainage_network.py \
  --network_definition network_config.yaml \
  --output_dir outputs/swmm_run/network/
```

**Critical**: Invert elevations must decrease in the downstream direction (toward the outfall). Adverse slopes (water flowing uphill) cause instability in dynamic wave routing. See dt_002.

**Aponded**: Set > 0 if ALLOW_PONDING=YES in [OPTIONS]. This determines how much water can pond on the surface when the junction floods. A typical urban intersection might have Aponded = 500-2000 m2.

### Step 2: Define Conduit Links

Conduits are pipes and open channels connecting junction nodes. Each conduit needs:

| Parameter | Description | Units (CMS) | Typical Range |
|-----------|-------------|-------------|---------------|
| ID | Unique identifier | string | "C1", "PIPE_001" |
| From_Node | Upstream junction ID | string | Must exist in junctions |
| To_Node | Downstream junction ID | string | Must exist in junctions or outfalls |
| Length | Pipe length | meters | 10 - 1000 |
| Roughness | Manning's n | dimensionless | 0.010 - 0.025 |
| InOffset | Inlet offset from From_Node invert | meters | >= 0 |
| OutOffset | Outlet offset from To_Node invert | meters | >= 0 |

Manning's roughness by pipe material:
| Material | Manning's n |
|----------|------------|
| PVC | 0.009-0.011 |
| Concrete (good condition) | 0.012-0.014 |
| Concrete (poor condition) | 0.014-0.017 |
| Corrugated metal | 0.022-0.026 |
| Cast iron (coated) | 0.011-0.014 |
| Brick sewer | 0.013-0.017 |
| Earth channel | 0.018-0.030 |
| Natural channel (clean) | 0.025-0.040 |
| Natural channel (weedy) | 0.030-0.050 |

**Zero-length conduits**: SWMM crashes or produces NaN results if a conduit has length = 0. This happens when two junctions are at the exact same coordinates. Always check for zero-length conduits. See dt_007.

### Step 3: Import from GIS (Optional)

If pipe network data is available as GIS shapefiles:

```bash
python tools/s2_drainage_network/import_network_from_gis.py \
  --junction_shapefile data/gis/manholes.shp \
  --conduit_shapefile data/gis/pipes.shp \
  --id_field MANHOLE_ID \
  --elev_field INVERT_EL \
  --diameter_field DIAMETER \
  --material_field MATERIAL \
  --output_dir outputs/swmm_run/network/
```

Common GIS data issues:
- **Disconnected pipe segments**: Pipe endpoints do not snap to manhole locations. Use a spatial tolerance (0.1-1.0m) to snap endpoints to nearest junctions.
- **Missing attributes**: Elevation or diameter fields are NULL for some features. Fill with interpolated values or flag for manual review.
- **Diameter units**: GIS data may store diameter in mm (e.g., 600) while SWMM expects meters (0.6) for CMS. Always verify and convert.
- **Duplicate nodes**: Multiple manhole features at the same location. Merge duplicates.

### Step 4: Define Cross-Sections

```bash
python tools/s2_drainage_network/define_cross_sections.py \
  --conduit_list xsection_config.json \
  --output_csv outputs/swmm_run/network/xsections.csv
```

Standard cross-section shapes:
| Shape | Geom1 | Geom2 | Geom3 | Geom4 | Description |
|-------|-------|-------|-------|-------|-------------|
| CIRCULAR | diameter | — | — | — | Round pipe |
| RECT_CLOSED | height | width | — | — | Box culvert |
| RECT_OPEN | height | width | — | — | Open channel |
| TRAPEZOIDAL | height | bottom_width | left_slope | right_slope | Trapezoidal channel |
| TRIANGULAR | height | top_width | — | — | V-ditch |
| ARCH | height | width | — | — | Arch pipe |
| IRREGULAR | transect_ID | — | — | — | Custom HEC-RAS transect |

**Geom1 is in the unit system set by FLOW_UNITS**: meters for CMS, feet for CFS. If FLOW_UNITS=CMS and you enter a pipe diameter of 600 (meaning 600mm), SWMM interprets it as 600 meters. This is a SILENT ERROR. See dt_004.

### Step 5: Define Outfall Nodes

At least one outfall must exist. Outfalls define where water leaves the drainage system. Boundary types:

| Type | Description | Additional Data |
|------|-------------|-----------------|
| FREE | Critical/normal depth at outfall | None |
| NORMAL | Normal depth based on slope | None |
| FIXED | Fixed water level | Stage (elevation) |
| TIDAL | Tidal variation | Tidal curve |
| TIMESERIES | Time-varying boundary | Time series name |

Use TIMESERIES for CaMa-Flood coupling (receiving river stage as boundary condition).

### Step 6: Validate Network Connectivity

```bash
python tools/s2_drainage_network/validate_network_connectivity.py \
  --network_dir outputs/swmm_run/network/ \
  --subcatchment_config outputs/swmm_run/subcatchments/all_params.csv
```

The validator checks:
1. Every junction can reach an outfall via conduit paths (graph reachability)
2. No isolated subgraphs (disconnected pipe segments)
3. No zero-length conduits
4. Conduit slopes are not adverse (optional warning)
5. Every subcatchment outlet exists as a node

## Expected Outputs

| Output | Path Pattern | Description |
|--------|-------------|-------------|
| Junction data | `{output_dir}/junctions.csv` | All junction parameters |
| Conduit data | `{output_dir}/conduits.csv` | All conduit parameters |
| Outfall data | `{output_dir}/outfalls.csv` | Outfall parameters and boundary types |
| Cross-section data | `{output_dir}/xsections.csv` | Cross-section geometry |
| Connectivity report | (stdout/JSON) | Graph analysis results |

## Validation Checks

1. **Connectivity**: Every junction reaches an outfall (graph traversal)
2. **No zero-length conduits**: All conduit lengths > 0
3. **No duplicate IDs**: Node and link IDs are unique
4. **Invert continuity**: Upstream invert >= downstream invert for each conduit (warns on adverse slopes)
5. **Cross-section completeness**: Every conduit has a cross-section defined
6. **Outfall exists**: At least one outfall in the system
7. **Dimensions positive**: All diameters, widths, heights > 0
8. **Manning's n valid**: Roughness in [0.005, 0.100]

## Common Pitfalls

**No outfall defined (FATAL)**: SWMM requires at least one outfall. Without an outfall, water enters the system but has nowhere to exit, causing immediate flooding and instability. See dt_008.

**Zero-length conduit (FATAL)**: Causes division by zero in hydraulic computations. Usually results from two junctions at the same coordinates with a connecting pipe. Merge the junctions or set a minimum length (e.g., 1m). See dt_007.

**Adverse conduit slopes**: When inlet invert + offset > outlet invert + offset, water must flow uphill. Dynamic wave can handle this (pressurized flow) but it causes numerical oscillations and instability. Kinematic wave cannot handle adverse slopes at all. See dt_002.

**Dimension unit mismatch**: Pipe diameter in mm when FLOW_UNITS expects meters (CMS) or feet (CFS). SWMM has no dimension validation — it trusts the numbers you give it. See dt_004.

**Incorrect offsets**: Inlet/outlet offsets are measured from the junction invert, not from the pipe invert. A pipe crown at junction invert level has offset = 0, not offset = diameter.

**Missing max_depth on junctions**: If max_depth = 0, the junction has zero capacity and floods immediately. Set max_depth to at least the largest connected pipe diameter, typically 1.5-3.0 meters for manholes.

## Tools Reference

| Tool ID | Script | Purpose |
|---------|--------|---------|
| `create_drainage_network` | `tools/s2_drainage_network/create_drainage_network.py` | Define network from manual specs |
| `import_network_from_gis` | `tools/s2_drainage_network/import_network_from_gis.py` | Import from GIS shapefiles |
| `define_cross_sections` | `tools/s2_drainage_network/define_cross_sections.py` | Define conduit cross-sections |
| `validate_network_connectivity` | `tools/s2_drainage_network/validate_network_connectivity.py` | Validate network graph |
