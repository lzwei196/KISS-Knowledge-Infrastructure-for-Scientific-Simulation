> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model.
>
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (4 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (15 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/flowline_converter.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/flowline_converter.py --help` |
| `tools/mesh_converter.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/mesh_converter.py --help` |
| `tools/output_parser.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/output_parser.py --help` |
| `tools/run_hexwatershed.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_hexwatershed.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# HexWatershed — Knowledge Infrastructure

**Package**: `hexwatershed-coastal` v1.0.0
**Model**: HexWatershed (C++ mesh-independent flow direction model)
**Created by**: Chang Liao, Pacific Northwest National Laboratory (PNNL)
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 18 diagnostic triplets | ~8000 lines of C++

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## Overview

HexWatershed is a mesh-independent flow direction model for watershed delineation on
unstructured meshes—primarily hexagonal grids but also supporting square, lat/lon,
MPAS, DGGRID, and TIN meshes. Unlike traditional raster-based watershed models
(e.g., D8 on square grids), HexWatershed operates on arbitrary polygonal meshes,
eliminating the directional bias inherent in 4- or 8-connected square grids.

The model implements the Priority-Flood depression filling algorithm, steepest-descent
flow direction, topological flow accumulation, stream burning, and full watershed
delineation (segments, subbasins, hillslopes, Strahler order). It is the C++ backend
of the **PyFlowline/PyHexWatershed** Python ecosystem.

**Key reference:** Liao, C., Tesfa, T., Duan, Z., & Leung, L. R. (2020). Watershed
delineation on a hexagonal mesh grid. *Environmental Modelling & Software*, 128, 104702.

---

## Installation

### Build from Source (CMake)

```bash
cd /path/to/hexwatershed/src/repo
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
# Binary: build/hexwatershed
```

### Dependencies

| Dependency   | Type     | Notes                              |
|-------------|----------|------------------------------------|
| C++11       | Required | Standard library only              |
| CMake ≥3.1  | Required | Build system                       |
| RapidJSON   | Bundled  | Header-only, in external/          |
| OpenMP      | Optional | Auto-detected, parallel loops      |

### Python Ecosystem (for pre/post-processing)

```bash
pip install pyflowline pyhexwatershed
```

PyFlowline generates the mesh JSON that HexWatershed consumes.

### Quick Test

```bash
hexwatershed /path/to/config.json
```

---

## Pipeline (6 stages)

| # | Stage                  | Tool(s)                          | Description                                          |
|---|------------------------|----------------------------------|------------------------------------------------------|
| 0 | Configuration          | —                                | Prepare JSON config and basin definitions             |
| 1 | Mesh Generation        | `mesh_converter.py`              | Generate mesh JSON via PyFlowline or convert DEM      |
| 2 | Stream Preparation     | `flowline_converter.py`          | Convert NHD/global flowlines to model format          |
| 3 | Execution              | `run_hexwatershed.py`            | Run the hexwatershed binary                           |
| 4 | Output Parsing         | `output_parser.py`               | Extract watershed results to CSV/GeoJSON              |
| 5 | Validation             | (manual / diagnostic scripts)    | Compare results against reference data                |

**Notes:**
- Stages 1-2 can run in parallel (mesh and flowlines are independent).
- Stage 3 requires both mesh JSON and (optionally) flowline data.
- PyFlowline must be used to generate the mesh input before HexWatershed can run.

---

## Tools Reference

| Tool                    | Stage | Script                      | Purpose                                           |
|------------------------|-------|-----------------------------|---------------------------------------------------|
| Mesh Converter         | s1    | `tools/mesh_converter.py`    | Convert DEM/shapefile to HexWatershed mesh JSON   |
| Flowline Converter     | s2    | `tools/flowline_converter.py`| Convert NHD/global flowlines to basin JSON format |
| Execution Wrapper      | s3    | `tools/run_hexwatershed.py`  | Build config JSON and run the binary              |
| Output Parser          | s4    | `tools/output_parser.py`     | Parse watershed JSON outputs to CSV               |

---

## Execution Model

### CLI Invocation

```bash
hexwatershed <configuration_file.json>
```

The single argument is a JSON configuration file. No other CLI flags exist.

### Internal Workflow (inside the binary)

```
domain_setup()
  └─ domain_read()
       ├─ domain_read_configuration_file()   # Parse JSON config
       ├─ domain_retrieve_user_input()        # Extract parameters
       └─ domain_read_input_data()            # Load mesh + elevation
  └─ domain_initialize()
       └─ compset_initialize()               # Build cell topology
  └─ domain_run()
       └─ compset_run_model()
            ├─ priority_flood_depression_filling()
            ├─ calculate_flow_direction()
            ├─ stream_burning()              # if iFlag_flowline=1
            ├─ calculate_flow_accumulation()
            ├─ define_stream_grid()
            ├─ define_watershed_boundary()
            ├─ define_stream_confluence()
            ├─ define_stream_segment()
            ├─ build_stream_topology()
            ├─ define_stream_order()
            ├─ define_subbasin()
            └─ calculate_watershed_characteristics()
  └─ domain_export()
       └─ compset_export()                   # Write JSON + VTK + text
  └─ domain_cleanup()
```

---

## Configuration Reference

### Main Configuration File (JSON)

| Parameter                        | Type    | Default  | Description                                    |
|---------------------------------|---------|----------|------------------------------------------------|
| `sMesh_type`                    | string  | —        | Mesh type: hexagon, square, latlon, mpas, dggrid, tin |
| `iFlag_global`                  | int     | 0        | Global simulation (1) vs regional (0)          |
| `iFlag_flowline`                | int     | 0        | Enable stream burning from flowlines           |
| `iFlag_multiple_outlet`         | int     | 0        | Multiple watershed outlets                     |
| `iFlag_stream_grid_option`      | int     | 2        | 1=burned-in, 2=accumulation threshold          |
| `iFlag_stream_burning_topology` | int     | 0        | Use topology for stream burning                |
| `iFlag_hillslope`               | int     | 0        | Calculate hillslope attributes                 |
| `iFlag_animation`               | int     | 0        | Generate animation JSON                        |
| `iFlag_vtk`                     | int     | 0        | Generate VTK 3D output                         |
| `iFlag_debug`                   | int     | 0        | Debug mode with extra output                   |
| `iFlag_elevation_profile`       | int     | 0        | Compute elevation profiles per subbasin        |
| `iFlag_resample_method`         | int     | 1        | DEM resampling: 1=nearest, 2=mean             |
| `nOutlet`                       | long    | 1        | Number of watershed outlets                    |
| `iCase_index`                   | int     | 1        | Case identifier for batch runs                 |
| `dMissing_value_dem`            | float   | -9999.0  | DEM nodata sentinel                            |
| `dAccumulation_threshold`       | float   | 0.01     | Stream threshold (<1.0=ratio, ≥1.0=absolute)  |
| `dBreach_threshold`             | float   | 0.0      | Elevation jump limit for breaching (m)         |
| `sWorkspace_input`              | string  | —        | Input directory path                           |
| `sWorkspace_output`             | string  | —        | Output root directory                          |
| `sWorkspace_output_hexwatershed`| string  | —        | HexWatershed-specific output directory         |
| `sFilename_basins`              | string  | —        | Path to basin configuration JSON               |
| `sDate`                         | string  | —        | Simulation date label                          |

### Basin Configuration File (JSON, when iFlag_flowline=1)

| Parameter                       | Type    | Description                             |
|--------------------------------|---------|------------------------------------------|
| `lCellID_outlet`               | long    | Outlet cell ID from mesh                 |
| `lBasinID`                     | long    | Basin identifier                         |
| `dLatitude_outlet_degree`      | float   | Outlet latitude (GCS degrees)            |
| `dLongitude_outlet_degree`     | float   | Outlet longitude (GCS degrees)           |
| `dAccumulation_threshold_ratio`| float   | Stream threshold ratio for this basin    |
| `dThreshold_small_river`       | float   | Remove rivers below this threshold       |
| `sFilename_flowline_raw`       | string  | Path to raw flowline shapefile           |
| `sFilename_flowline_filter`    | string  | Path to filtered flowline                |
| `sFilename_flowline_topo`      | string  | Path to topological flowline             |

---

## Input Data Formats

### Mesh Information JSON

Generated by PyFlowline. Contains cell array with:

| Field                      | Type         | Unit           | Description                   |
|---------------------------|--------------|----------------|-------------------------------|
| `lCellID`                 | long         | —              | Global unique cell ID         |
| `dElevation_mean`         | float        | m              | Mean cell elevation           |
| `dElevation_raw`          | float        | m              | Raw (unprocessed) elevation   |
| `dLongitude_center_degree`| float        | degrees        | Cell center longitude (GCS)   |
| `dLatitude_center_degree` | float        | degrees        | Cell center latitude (GCS)    |
| `dArea`                   | double       | m²             | Cell area                     |
| `vVertex`                 | array[vertex]| degrees        | Polygon vertices (GCS)        |
| `aNeighbor`               | array[long]  | —              | Neighbor cell IDs             |
| `aNeighbor_distance`      | array[float] | m              | Distance to each neighbor     |

### DEM Requirements

- **CRS**: Geographic Coordinate System (lat/lon degrees)
- **Elevation unit**: meters
- **Nodata**: Must match `dMissing_value_dem` in config (typically -9999.0)
- **Coverage**: Must cover entire mesh extent

---

## 6. Output Description

**SOURCE OF RECORD: `dag.yaml`.** The dag is the model identity for outputs and validation:
when this section disagrees with the dag, the dag wins.

### 6.1 Headline Output

`dElevation_mean (depression-filled elevation)` is the dag's `validation_rank: 1`
variable and the output this KI judges first.

> `dElevation_mean (depression-filled elevation)` — Per-cell elevation after Priority-Flood depression filling; the surface all downstream analysis uses (raw retained in dElevation_raw). (m)

### 6.2 Observable Dag Outputs

| Output variable (dag `var`) | Rank | Unit | Dag fact restated here |
|-----------------------------|------|------|------------------------|
| `dElevation_mean (depression-filled elevation)` | 1 | m | Per-cell elevation after Priority-Flood depression filling; the surface all downstream analysis uses (raw retained in dElevation_raw). |
| `lCellID_downslope_dominant (flow direction)` | dag output | see `dag.yaml` | Listed as another dag output. |
| `dAccumulation (flow accumulation)` | dag output | see `dag.yaml` | Listed as another dag output. |
| `Drainage area (derived watershed/contributing area)` | dag output | see `dag.yaml` | Listed as another dag output. |
| `Stream grid / stream network (iFlag_stream, segments)` | dag output | see `dag.yaml` | Listed as another dag output. |
| `Strahler stream order` | dag output | see `dag.yaml` | Listed as another dag output. |
| `Watershed boundary / subbasin boundaries` | dag output | see `dag.yaml` | Listed as another dag output. |
| `Mean / max / min watershed slope` | dag output | see `dag.yaml` | Listed as another dag output. |
| `Drainage density` | dag output | see `dag.yaml` | Listed as another dag output. |

HexWatershed writes per-watershed results to JSON (GeoJSON) and plain-text files in the output directory. The primary output is `watershed_NNNNN.json` containing per-cell flow direction, flow accumulation (cell count), depression-filled elevation, slope, and stream/subbasin assignments. Companion text files (`*_characteristics.txt`) summarize watershed area, drainage density, stream lengths, and Strahler order. Optional VTK files are generated when `iFlag_vtk=1` for 3D visualization. Use `output_parser.py` to convert JSON outputs to CSV or GeoJSON for GIS analysis. See detailed format descriptions below.

## Output Data Formats

### Per-Watershed JSON (GeoJSON)

File: `watershed_NNNNN.json`

| Field                        | Type    | Unit    | Description                        |
|-----------------------------|---------|---------|-------------------------------------|
| `lCellID`                   | long    | —       | Cell identifier                     |
| `dElevation_mean`           | float   | m       | Depression-filled elevation         |
| `dElevation_raw`            | float   | m       | Original elevation                  |
| `dAccumulation`             | double  | cells   | Flow accumulation (cell count)      |
| `dSlope_between`            | float   | ratio   | Slope to downslope neighbor         |
| `dSlope_within`             | float   | ratio   | Internal fine-scale slope           |
| `dDistance_to_downslope`    | float   | m       | Distance to dominant downslope      |
| `dDistance_to_channel`      | float   | m       | Overland distance to stream         |
| `dDistance_to_watershed_outlet`| float | m       | Travel distance to outlet           |
| `lCellID_downslope`        | long    | —       | Dominant downslope cell ID          |
| `lStream_segment`          | long    | —       | Associated stream segment           |
| `lSubbasin`                | long    | —       | Associated subbasin                 |
| `lHillslope`               | long    | —       | Associated hillslope                |
| `vVertex`                  | array   | degrees | Polygon vertices (GCS)              |

### Watershed Characteristics (text)

File: `watershed_NNNNN_characteristics.txt`

- Total area (m²)
- Mean/max/min slope (unitless ratio)
- Total stream length (m), longest stream (m)
- Drainage density (km/km² = km⁻¹)
- Number of cells, segments, confluences, subbasins
- Outlet location (lat/lon degrees)

### Segment Characteristics (text)

- Segment ID, watershed, downstream segment
- Length (m), elevation drop (m), mean slope
- Strahler stream order, headwater flag

### Subbasin Characteristics (text)

- Subbasin ID, area (m²), mean slope
- Left/right/headwater hillslope dimensions (length m, width m, area m², slope)
- Elevation profiles (11-point array per hillslope)

---

## 8. Unit Conversion Table

**SOURCE OF RECORD: `dag.yaml`, `docs/format_spec.yaml`, and the field/output definitions above.**
Exact I/O shapes live in `docs/format_spec.yaml`; this table records the unit handling an
agent must preserve when preparing inputs or post-processing outputs.

| Variable | Source unit (verified) | Model/output unit | Factor | Type |
|----------|------------------------|-------------------|--------|------|
| DEM elevation / `dElevation_raw` | m | m | x1 | none |
| `dElevation_mean (depression-filled elevation)` | m | m | x1 | none |
| `dAccumulation (flow accumulation)` | cells | cells | x1 | none |
| Drainage area (derived watershed/contributing area) | cells and cell area in m2 | m2 or km2, depending on reporting target | multiply `dAccumulation` by cell area; divide by 1,000,000 for km2 | derived |
| Coordinates / mesh vertices | degrees (GCS) | degrees (GCS) | x1 | none |
| Cell area | m2 | m2 | x1 | none |
| Neighbor distance / flow path distance | m | m | x1 | none |
| Slope outputs | elevation difference / horizontal distance | unitless ratio | x1 | none |
| Stream length | m | m; convert to km for drainage-density numerator | divide by 1,000 for km | derived |
| Drainage density | stream length and watershed area | km/km2 | stream length m to km; area m2 to km2 | derived |

## Unit Trap Table

| Variable               | Expected Unit         | Common Trap                              | Impact            |
|-----------------------|----------------------|------------------------------------------|--------------------|
| Elevation (DEM)       | meters               | Feet from USGS NED → 3× inflated slopes | Silent: wrong flow |
| Coordinates           | degrees (GCS)        | Projected CRS (meters) → broken geometry | Fatal: crash       |
| Cell area             | m²                   | km² from GIS → 10⁶× error in drainage   | Silent: bad metrics|
| Neighbor distance     | meters               | km or degrees → wrong slope calc         | Silent: wrong flow |
| Accumulation threshold| ratio (<1.0) or cells| Confusing ratio vs absolute → too few/many streams | Degraded |
| Breach threshold      | meters               | Set to 0 → no breaching → disconnected streams | Silent   |
| Missing value         | must match DEM nodata| Mismatch → valid cells treated as nodata | Silent: holes      |
| Slope output          | unitless ratio (Δz/Δd)| Interpreted as degrees or percent       | Silent: wrong TWI  |
| Drainage density      | km⁻¹                | Computed from m → must convert area to km²| Silent: 10⁶× off  |
| Flowline coordinates  | GCS degrees          | Projected → flowlines don't intersect mesh| Fatal: no burning |

---

## Critical Domain Knowledge

### dt_001: Depression Filling Modifies Elevation Permanently
The Priority-Flood algorithm fills depressions by raising `dElevation_mean` to the
pour-point level. This means all downstream analyses use the **filled** DEM, not the
raw DEM. If you compare output elevations to raw input, they WILL differ in depression
areas. The raw elevation is preserved in `dElevation_raw`.

### dt_002: Flow Accumulation Is Cell Count, Not Area
`dAccumulation` stores the **number of upstream cells**, not the upstream contributing
area in m². To get drainage area, multiply by mean cell area. The accumulation threshold
(`dAccumulation_threshold`) operates on this cell count (or ratio of max count).

### dt_003: Slope Is a Unitless Ratio, Not Degrees
All slope outputs (`dSlope_between`, `dSlope_max_downslope`, etc.) are computed as
`elevation_difference / horizontal_distance` (rise/run), producing a dimensionless
ratio. They are NOT expressed in degrees or percent. A slope of 0.1 means 10% grade.

### dt_004: Stream Burning Requires PyFlowline Preprocessing
When `iFlag_flowline=1`, the model expects pre-processed flowline data from PyFlowline.
Raw NHD or HydroSHEDS flowlines must first be converted to the model's topological
format with cell-to-flowline mapping. Providing raw shapefiles will cause silent failures.

### dt_005: Mesh Type Must Match Input JSON Structure
The `sMesh_type` parameter selects the parser for the mesh JSON. If the mesh was
generated as "hexagon" but config says "mpas", the parser will fail or silently
misinterpret the cell connectivity. Always verify consistency.

### dt_006: Coordinate System Must Be Geographic (GCS)
All coordinates in the mesh JSON must be in geographic degrees (WGS84/EPSG:4326).
The model internally converts to 3D Cartesian for distance calculations. Projected
coordinates (UTM, State Plane) will produce nonsensical distances and areas.

### dt_007: Accumulation Threshold Dual Interpretation
If `dAccumulation_threshold < 1.0`, it is treated as a **ratio** of the maximum
accumulation. If `≥ 1.0`, it is the **absolute cell count**. Accidentally using 100
(meaning "100 cells") vs 0.01 (meaning "top 1% drainage area") produces wildly
different stream networks.

### dt_008: Multiple Outlet Mode Requires Consistent Basin IDs
When `iFlag_multiple_outlet=1`, each basin's `lBasinID` and `lCellID_outlet` must
correspond to actual mesh cells. Incorrect outlet cell IDs cause the entire watershed
to be skipped silently.

### dt_009: VTK Output Requires iFlag_vtk=1 Explicitly
VTK files for 3D visualization are only generated when `iFlag_vtk=1`. This is not
the default. Without it, only JSON and text outputs are produced.

### dt_010: Hillslope Attributes Require iFlag_hillslope=1
Left/right/headwater hillslope decomposition and elevation profiles are computed
only when `iFlag_hillslope=1`. Subbasin output will lack hillslope columns otherwise.

---

## Supported Mesh Types

| Code | sMesh_type | Description                       | Typical Use Case              |
|------|-----------|-----------------------------------|-------------------------------|
| 1    | hexagon   | Regular hexagonal grid            | Regional watersheds           |
| 2    | square    | Square/rectangular grid           | Comparison with D8            |
| 3    | latlon    | Lat/lon regular grid              | Global climate model grids    |
| 4    | mpas      | MPAS unstructured mesh            | E3SM/MPAS ocean coupling      |
| 5    | dggrid    | Discrete Global Grid (ISEA)       | Global multi-resolution       |
| 6    | tin       | Triangulated Irregular Network    | Adaptive resolution           |

---

## Key Algorithms

### Priority-Flood Depression Filling
Iterative filling that raises cells in local minima to the elevation of the lowest
pour point. Ensures every cell has a valid downslope path. Convergence is guaranteed
for finite meshes.

### Steepest-Descent Flow Direction
For each cell, the neighbor with the maximum slope (Δz/distance) is selected as the
dominant downslope direction. Ties are broken by cell ID. Two modes exist:
- **Elevation-based** (default): Pure topographic routing.
- **Topology-based** (`iFlag_stream_burning_topology=1`): Uses known stream network
  topology to constrain directions along burned-in channels.

### Stream Burning
Modifies flow directions along known stream channels. The breaching algorithm limits
elevation jumps at crossings to `dBreach_threshold` meters, preventing artificial dams
at road crossings or mesh artifacts.

### Topological Flow Accumulation
Cells are processed from headwaters (zero upslope neighbors) toward outlets. Each cell
accumulates the count of all upstream cells plus itself. The algorithm uses iterative
peeling rather than recursion.

---

## Data Requirements

| Data                | Source                   | Format            | Notes                     |
|--------------------|--------------------------|-------------------|---------------------------|
| DEM                | SRTM / MERIT / NED       | GeoTIFF (→ JSON)  | Must be GCS, meters       |
| Mesh definition    | PyFlowline output         | JSON              | Cell topology + elevation |
| Flowlines          | NHDPlus / HydroSHEDS      | Shapefile (→ JSON)| Optional, for burning     |
| Basin outlets      | User-defined              | JSON              | Lat/lon + cell IDs        |

---

## Quick Start

```bash
# 1. Build the binary
cd hexwatershed/src/repo && mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release && make -j4

# 2. Prepare mesh with PyFlowline (Python)
python -c "
from pyflowline.formats.convert_mesh import pyflowline_generate_mesh
pyflowline_generate_mesh(sDEM='/data/dem.tif', sMesh_type='hexagon',
                          dResolution=5000, sOutput='/data/mesh/')
"

# 3. Create config JSON
cat > config.json << 'EOF'
{
  "sMesh_type": "hexagon",
  "iFlag_global": 0,
  "iFlag_flowline": 0,
  "iFlag_stream_grid_option": 2,
  "dAccumulation_threshold": 0.01,
  "dMissing_value_dem": -9999.0,
  "nOutlet": 1,
  "sWorkspace_input": "/data/mesh",
  "sWorkspace_output": "/data/output",
  "sWorkspace_output_hexwatershed": "/data/output/hexwatershed"
}
EOF

# 4. Run the model
./hexwatershed config.json

# 5. Parse outputs
python output_parser.py --input /data/output/hexwatershed --output /data/results.csv
```

---

## 9. Diagnostic Triplets Summary

| ID     | Stage | Severity | Domain           | Summary                                    |
|--------|-------|----------|------------------|--------------------------------------------|
| dt_001 | s3    | silent   | algorithm        | Depression filling changes elevations       |
| dt_002 | s4    | silent   | unit_conversion  | Accumulation is cells, not area             |
| dt_003 | s4    | silent   | unit_conversion  | Slope is ratio, not degrees                 |
| dt_004 | s2    | fatal    | dependency       | Stream burning needs PyFlowline prep        |
| dt_005 | s1    | fatal    | parameter_format | Mesh type must match JSON structure         |
| dt_006 | s1    | fatal    | unit_conversion  | Coordinates must be GCS degrees             |
| dt_007 | s0    | degraded | parameter_format | Threshold dual interpretation (ratio vs abs)|
| dt_008 | s0    | silent   | parameter_format | Wrong outlet cell IDs → skipped watershed   |
| dt_009 | s0    | degraded | parameter_format | VTK output not generated by default         |
| dt_010 | s0    | degraded | parameter_format | Hillslope needs explicit flag               |
| dt_011 | s1    | silent   | unit_conversion  | Cell area in m², not km²                    |
| dt_012 | s1    | silent   | unit_conversion  | Neighbor distance in m, not km              |
| dt_013 | s3    | silent   | unit_conversion  | DEM in feet → inflated slopes               |
| dt_014 | s0    | fatal    | parameter_format | Missing value mismatch with DEM             |
| dt_015 | s2    | fatal    | unit_conversion  | Flowline coords must be GCS                 |
| dt_016 | s4    | silent   | unit_conversion  | Drainage density requires km conversion     |
| dt_017 | s3    | degraded | algorithm        | Breach threshold 0 → no breaching           |
| dt_018 | s3    | silent   | algorithm        | Topology mode without topology file         |

---

## 11. Validated Results

The body validation campaign is pending. No calibration, validation, or full-period
performance scores are stated in this SKILL body; judge any future run against
`docs/validation_convention.yaml`, not against intuition or remembered thresholds.

### 11.1 Convention Bars

**SOURCE OF RECORD: `docs/validation_convention.yaml`.** The convention wins over
prose. Bands with null convention thresholds are written as "no cited threshold";
do not substitute guessed values.

| Dag variable | Metric | Direction | Satisfactory band | Good band | Very good band |
|--------------|--------|-----------|-------------------|-----------|----------------|
| `dElevation_mean (depression-filled elevation)` | `csi` | maximize | no cited threshold | no cited threshold | no cited threshold |
| `dElevation_mean (depression-filled elevation)` | `rmse` | minimize | no cited threshold | no cited threshold | no cited threshold |
| `lCellID_downslope_dominant (flow direction)` | `upstream_area_me` | maximize | >= 0.69 (`yamazaki2009_flow`) | >= 0.9 (`yamazaki2009_flow`) | >= 0.99 (`yamazaki2009_flow`) |
| `dAccumulation (flow accumulation)` | `upstream_area_me` | maximize | >= 0.69 (`yamazaki2009_flow`) | >= 0.9 (`yamazaki2009_flow`) | >= 0.99 (`yamazaki2009_flow`) |

### 11.2 Performance Metrics

| Metric | Calibration | Validation | Full Period | Bar (convention, cited) |
|--------|-------------|------------|-------------|-------------------------|
| `csi` for `dElevation_mean (depression-filled elevation)` | pending | pending | pending | no cited threshold |
| `rmse` for `dElevation_mean (depression-filled elevation)` | pending | pending | pending | no cited threshold |
| `upstream_area_me` for `lCellID_downslope_dominant (flow direction)` | pending | pending | pending | satisfactory >= 0.69 (`yamazaki2009_flow`), good >= 0.9 (`yamazaki2009_flow`), very good >= 0.99 (`yamazaki2009_flow`) |
| `upstream_area_me` for `dAccumulation (flow accumulation)` | pending | pending | pending | satisfactory >= 0.69 (`yamazaki2009_flow`), good >= 0.9 (`yamazaki2009_flow`), very good >= 0.99 (`yamazaki2009_flow`) |

### 11.3 Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| DEM / topography | Pipeline | Pending | Feeds `dElevation_raw` and the depression-filled headline output. |
| Mesh definition | PyFlowline / mesh converter | Pending | Provides cell topology, area, coordinates, and neighbor distances. |
| Flowlines | Flowline converter | Pending | Optional stream burning input when `iFlag_flowline=1`. |
| Basin outlets | User basin configuration | Pending | Required for watershed and subbasin delineation. |
| Output validation | Validation convention | Pending | Use the bars above and the full convention file. |

---

## File Structure

```
hexwatershed/
├── src/repo/
│   ├── CMakeLists.txt                  # Build system
│   ├── external/rapidjson/             # Bundled JSON library
│   └── src/
│       ├── main.cpp                    # Entry point (argc==2)
│       ├── hexagon.h/.cpp              # Core cell class (60+ fields)
│       ├── watershed.h/.cpp            # Watershed container
│       ├── segment.h/.cpp              # Stream segment
│       ├── subbasin.h/.cpp             # Subbasin with hillslopes
│       ├── parameter.h/.cpp            # Config parsing
│       ├── domain/                     # Domain setup/read/export
│       ├── compset/                    # Core algorithms
│       │   ├── compset_depression.cpp  # Priority-Flood
│       │   ├── compset_direction.cpp   # Flow direction
│       │   ├── compset_stream.cpp      # Stream burning
│       │   ├── compset_run.cpp         # Workflow orchestration
│       │   └── compset_export.cpp      # Output generation
│       └── json/                       # JSON I/O classes
├── ki/                                 # Knowledge Infrastructure
│   ├── SKILL.md                        # This file
│   ├── tools/                          # Python helper scripts
│   ├── docs/                           # Per-stage skill documents
│   └── diagnostics/                    # Triplets + error logs
└── figures/                            # Validation figures
```

---

## Variable Naming Conventions

| Prefix | Type           | Example                |
|--------|----------------|------------------------|
| `d`    | float/double   | `dElevation_mean`      |
| `i`    | int            | `iFlag_stream`         |
| `l`    | long           | `lCellID`              |
| `s`    | string         | `sMesh_type`           |
| `v`    | vector         | `vNeighbor`            |
| `a`    | array          | `aNeighbor_distance`   |
| `n`    | count (int)    | `nVertex`              |
| `e`    | enum           | `eM_hexagon`           |

| Suffix          | Meaning                        |
|-----------------|--------------------------------|
| `_degree`       | Geographic coordinate (GCS)    |
| `_radian`       | Radian angle                   |
| `_mean`         | Averaged value                 |
| `_raw`          | Original unprocessed           |
| `_downslope`    | Steepest descent direction     |
| `_upslope`      | Steepest ascent direction      |
| `_burned`       | Related to stream burning      |
| `_index`        | Internal vector index          |
