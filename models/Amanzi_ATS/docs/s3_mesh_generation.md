# S3: Mesh Generation and Configuration

## Purpose

Generate or obtain a computational mesh for Amanzi/ATS simulations. Amanzi supports internally generated structured meshes and externally generated unstructured meshes in Exodus II format. Mesh quality and region labeling directly affect simulation accuracy and boundary condition assignment.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Domain dimensions | Problem definition | Length × Width × Depth | m |
| Cell resolution | User choice | nx, ny, nz counts | integer cells |
| Mesh file (external) | MSTK, Cubit, LaGriT | .exo (Exodus II) | m |
| Region definitions | Problem geometry | Labeled sets in .exo | integer IDs |

## Outputs

| Output | Format | Destination |
|--------|--------|-------------|
| Internal mesh spec | XML block | `<mesh><generate>` |
| External mesh reference | XML block | `<mesh><read>` |
| Region definitions | XML block | `<regions>` |

## Procedure

### Option A: Internal Mesh Generation (Simple Boxes)

For simple box-shaped domains, Amanzi can generate meshes internally:

```xml
<mesh framework="mstk">
  <dimension>3</dimension>
  <generate>
    <number_of_cells nx="100" ny="1" nz="50"/>
    <box low_coordinates="0.0,0.0,0.0" high_coordinates="100.0,1.0,50.0"/>
  </generate>
</mesh>
```

Key parameters:
- `framework`: "mstk" (recommended) or "simple"
- `dimension`: 2 or 3 (Amanzi always uses 3D internally; 2D is nx×1×nz)
- `nx, ny, nz`: Cell count in each direction
- `low_coordinates` / `high_coordinates`: Domain bounds in meters

### Option B: External Mesh (Exodus II)

For complex geometries, generate mesh externally and reference it:

```xml
<mesh framework="mstk">
  <dimension>3</dimension>
  <read>
    <file>mesh_file.exo</file>
    <format>exodus ii</format>
  </read>
</mesh>
```

External mesh tools:
- **Cubit/Trelis**: Commercial mesher with Exodus II export
- **LaGriT**: LANL mesh generator (tetrahedral, Voronoi)
- **MSTK**: Amanzi's built-in mesh toolkit
- **Gmsh** + conversion: Open-source mesher (requires format conversion)

### Region Definition

Regions link mesh subsets to materials, ICs, and BCs:

```xml
<regions>
  <!-- Box region (for internal meshes) -->
  <region name="Aquifer">
    <box low_coordinates="0.0,0.0,0.0" high_coordinates="100.0,1.0,30.0"/>
  </region>

  <!-- Plane region for boundary faces -->
  <region name="Top Surface">
    <plane location="0.0,0.0,50.0" normal="0.0,0.0,1.0"/>
  </region>

  <!-- Labeled set from Exodus mesh -->
  <region name="Upper Aquifer">
    <region_file label="30000" name="mesh.exo" type="labeled set"
                 format="exodus ii" entity="cell"/>
  </region>

  <!-- Point for observations -->
  <point name="Well_1" coordinate="50.0,0.5,25.0"/>
</regions>
```

## Verification

- Cell aspect ratio should be < 10:1 for numerical stability.
- Minimum 3 cells across the thinnest feature (aquitard, boundary layer).
- Region labels in XML must exactly match Exodus sideset/nodeset IDs.
- 2D simulations: set ny=1 and domain width = 1.0 m.

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| **dt_005** | Exodus label ID mismatch | BCs silently not applied |
| **dt_009** | 2D XML input with 3D mesh | Dimension error or wrong BC assignment |
| **dt_010** | Mesh file path wrong (relative vs absolute) | Fatal: file not found |

## Example

### 1D Column (100 cells, 10 m deep)

```xml
<mesh framework="mstk">
  <dimension>3</dimension>
  <generate>
    <number_of_cells nx="1" ny="1" nz="100"/>
    <box low_coordinates="0.0,0.0,0.0" high_coordinates="1.0,1.0,10.0"/>
  </generate>
</mesh>

<regions>
  <region name="Entire Domain">
    <box low_coordinates="0.0,0.0,0.0" high_coordinates="1.0,1.0,10.0"/>
  </region>
  <region name="Top Surface">
    <plane location="0.0,0.0,10.0" normal="0.0,0.0,1.0"/>
  </region>
  <region name="Bottom">
    <plane location="0.0,0.0,0.0" normal="0.0,0.0,-1.0"/>
  </region>
  <point name="Mid_Column" coordinate="0.5,0.5,5.0"/>
</regions>
```

### 2D Cross-Section (100 × 50 cells)

```xml
<mesh framework="mstk">
  <dimension>3</dimension>
  <generate>
    <number_of_cells nx="100" ny="1" nz="50"/>
    <box low_coordinates="0.0,0.0,0.0" high_coordinates="1000.0,1.0,50.0"/>
  </generate>
</mesh>
```
