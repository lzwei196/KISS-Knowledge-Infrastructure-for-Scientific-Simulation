# S1: Mesh Generation

## Purpose

Create the computational mesh that discretizes the physical domain into cells
where the governing equations are solved. Mesh quality directly controls
solution accuracy, convergence, and stability.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Domain extents | Physical dimensions | Coordinates | meters |
| Resolution | Accuracy requirements | Cell counts | - |
| Geometry | CAD model or dimensions | STL / coordinates | meters |
| Boundary patches | Physical boundaries | Name:type pairs | - |
| convertToMeters | Coordinate units | Scalar | - |

## Outputs

| Output | Location | Format |
|--------|----------|--------|
| blockMeshDict | system/blockMeshDict | OpenFOAM dictionary |
| polyMesh | constant/polyMesh/ | points, faces, owner, neighbour, boundary |
| checkMesh report | stdout | Text |

## Procedure

### Simple domains (blockMesh)

1. **Define vertices**: 8 corners of hex block in (x y z) format
2. **Set convertToMeters**: 1 if vertices in meters, 0.001 if mm, etc.
3. **Define blocks**: `hex (v0 v1 ... v7) (nx ny nz) grading`
4. **Define patches**: Group faces into inlet, outlet, walls, etc.
5. **Run blockMesh**: `blockMesh -case <caseDir>`
6. **Validate**: `checkMesh -case <caseDir>`

### Complex geometry (snappyHexMesh)

1. Create base mesh with blockMesh (coarse, enclosing domain)
2. Provide STL surface geometry (must be watertight)
3. Configure refinement levels in snappyHexMeshDict
4. Set boundary layer parameters (nLayers, expansionRatio)
5. Run: `snappyHexMesh -case <caseDir> -overwrite`

### Using generate_mesh.py

```bash
python generate_mesh.py \
    --case-dir ./channel \
    --x-range 0 10 \
    --y-range 0 1 \
    --z-range 0 0.1 \
    --nx 200 --ny 40 --nz 1 \
    --convert-to-meters 1 \
    --patches "inlet:patch,outlet:patch,topWall:wall,bottomWall:wall,frontAndBack:empty" \
    --run-blockmesh
```

## Verification

1. **checkMesh** must report:
   - Mesh OK (no fatal errors)
   - Max non-orthogonality < 70 degrees (ideally < 40)
   - Max skewness < 4 (ideally < 1)
   - Max aspect ratio < 100 (ideally < 20)

2. **Visual inspection**: Open in ParaView to verify:
   - Domain covers intended physical region
   - Patches are correctly assigned
   - Resolution adequate near walls and regions of interest

3. **Cell count**: Verify total cells matches expectations (nx * ny * nz)

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| convertToMeters wrong | Mesh at wrong scale, Re number off | Always verify domain dimensions in ParaView |
| Missing empty patch (2D) | Solver treats case as 3D, wrong results | Set nz=1 patches to type 'empty' |
| Non-watertight STL | snappyHexMesh fails or produces holes | Check STL with `surfaceCheck` utility |
| High non-orthogonality | Solver divergence | Add nNonOrthogonalCorrectors in fvSolution |
| Wrong vertex ordering | Negative cell volumes, mesh error | Follow OpenFOAM vertex numbering convention |
| Patch name mismatch | Fatal error when reading boundary conditions | Copy exact patch names to all field files |

## Example

Create mesh for lid-driven cavity (classic benchmark):
```bash
python generate_mesh.py \
    --case-dir ./cavity \
    --x-range 0 0.1 \
    --y-range 0 0.1 \
    --z-range 0 0.01 \
    --nx 20 --ny 20 --nz 1 \
    --convert-to-meters 1 \
    --patches "movingWall:wall,fixedWalls:wall,frontAndBack:empty" \
    --run-blockmesh
```

Expected output: 400 hex cells, max non-orthogonality = 0, max skewness = 0.
