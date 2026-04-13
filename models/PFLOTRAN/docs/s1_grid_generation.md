# S1: Grid Generation

## Purpose

Generate a computational mesh for the PFLOTRAN simulation domain. The grid
defines the spatial discretization of the subsurface, including cell geometry,
dimensions, and material zone assignments.

## Inputs

| Input | Format | Source | Units |
|---|---|---|---|
| Domain extent | Manual / GIS | DEM, geological maps | m |
| Horizontal resolution | Scalar | User choice | m |
| Vertical layer thicknesses | Array | Geological model | m |
| Grid type | Keyword | User choice | structured/unstructured |

## Outputs

| Output | Format | Used By |
|---|---|---|
| GRID block | PFLOTRAN .in text | s5_input_deck_assembly |
| REGION definitions | PFLOTRAN .in text | s5_input_deck_assembly |
| Mesh file (.h5 / .uge) | Binary (unstructured only) | s6_execution |

## Procedure

### Structured Grid (Cartesian)

1. Define domain bounds (x_min, y_min, z_min) to (x_max, y_max, z_max)
2. Choose cell counts: NXYZ nx ny nz
3. PFLOTRAN creates uniform cells: dx = (x_max - x_min) / nx

```
GRID
  TYPE STRUCTURED
  NXYZ 100 100 10
  BOUNDS
    0.d0 0.d0 0.d0
    10000.d0 10000.d0 100.d0
  /
END
```

For non-uniform spacing (thinner layers near surface):

```
GRID
  TYPE STRUCTURED
  NXYZ 100 100 10
  DXYZ
    100.d0       ! uniform 100m in x
    100.d0       ! uniform 100m in y
    0.5 0.5 1.0 1.0 2.0 5.0 10.0 20.0 30.0 31.0  ! variable z
  /
END
```

### Unstructured Grid

For irregular domains, use external mesh generators (e.g., LaGriT, Exodus II):

```
GRID
  TYPE UNSTRUCTURED mesh.h5
END
```

Or implicit unstructured format:

```
GRID
  TYPE UNSTRUCTURED_IMPLICIT
  NXYZ 50 50 10
  DOMAIN_FILENAME mesh.h5
END
```

### Region Definitions

Every boundary condition and initial condition requires a REGION:

```
REGION all
  COORDINATES
    0.d0 0.d0 0.d0
    10000.d0 10000.d0 100.d0
  /
END

REGION top
  FACE TOP
  COORDINATES
    0.d0 0.d0 100.d0
    10000.d0 10000.d0 100.d0
  /
END

REGION bottom
  FACE BOTTOM
  COORDINATES
    0.d0 0.d0 0.d0
    10000.d0 10000.d0 0.d0
  /
END

REGION west
  FACE WEST
  COORDINATES
    0.d0 0.d0 0.d0
    0.d0 10000.d0 100.d0
  /
END

REGION obs_well_1
  COORDINATE 5000.d0 5000.d0 50.d0
END
```

## Verification

1. Cell count = nx * ny * nz for structured grids
2. Total volume = sum of all cell volumes ≈ domain volume
3. No negative-volume cells (check PFLOTRAN startup output)
4. Observation points must fall within domain bounds
5. FACE regions must align with actual domain faces

## Traps

| Trap | Symptom | Fix |
|---|---|---|
| BOUNDS reversed | Domain has zero volume | Ensure min < max for all dimensions |
| DXYZ sum ≠ extent | Silent grid mismatch | Sum of DXYZ must equal BOUNDS range |
| Observation outside domain | No output for that obs point | Check COORDINATE vs BOUNDS |
| Too few vertical layers | Poor vadose zone resolution | Use ≥5 layers in top 2m |
| Z=0 at surface | Confusion with depth convention | PFLOTRAN uses Z=0 at bottom by default |

## Example

Bengbu Basin (~117°E, 33°N), 50km x 50km domain, 50m deep:

```
GRID
  TYPE STRUCTURED
  NXYZ 100 100 20
  BOUNDS
    0.d0 0.d0 0.d0
    50000.d0 50000.d0 50.d0
  /
END
```

Cells: 100 × 100 × 20 = 200,000
Resolution: 500m horizontal, 2.5m vertical
