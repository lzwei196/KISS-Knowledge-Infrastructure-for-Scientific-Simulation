# Stage 1: DFN Network Generation

## Purpose

Generate a 3D discrete fracture network (DFN) using the DFNGen C++ executable. Places fractures stochastically in the domain according to specified statistical distributions for size, orientation, and spatial density. Rejects fractures that violate geometric constraints (too close to existing fractures, outside domain, etc.).

## Prerequisites

- Stage 0 completed: all parameters configured and validated
- DFNGen v2.3 binary compiled (`DFNGen/DFNGen`)
- dfnWorks PATH set in `~/.dfnworksrc` or environment

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| Domain parameters | Stage 0 | Python dict | domainSize, h, seed, stopCondition |
| Fracture families | Stage 0 | Python list | Shape, distribution, orientation, size params |
| User-defined fracs | Stage 0 (optional) | Python/file | Explicit fracture coordinates |
| DFNGen binary | Compilation | Executable | `DFNGen/DFNGen` (v2.3 required) |

## Outputs

| Output | Path | Format | Description |
|--------|------|--------|-------------|
| params.txt | `<jobname>/params.txt` | Text | Generation summary, fracture count |
| radii_All.dat | `dfnGen_output/radii/` | DAT | All accepted fracture radii (meters) |
| Polygon data | `dfnGen_output/polys/` | DAT | Fracture polygon vertex coordinates |
| Intersection data | `dfnGen_output/intersections/` | DAT | Fracture-fracture intersection segments |
| Normal vectors | `<jobname>/normal_vectors.dat` | DAT | Unit normals for each fracture |
| Translations | `<jobname>/translations.dat` | DAT | Center coordinates for each fracture |
| dfngen_logfile.txt | `<jobname>/` | Text | Detailed generation log |

## Procedure

### Step 1: Create working directory

```python
DFN.make_working_directory(delete=True)  # delete=True overwrites existing
```

This creates the directory tree:
```
<jobname>/
  dfnGen_output/
    radii/
  intersections/
  polys/
```

### Step 2: Run DFNGen

```python
DFN.create_network()
```

Internally this:
1. Writes cleaned input file: `dfnGen_output/<jobname>_clean.dat`
2. Calls: `DFNGEN_EXE dfnGen_output/<jobname>_clean.dat <jobname>`
3. Checks for `params.txt` (success indicator)
4. Calls `gather_dfn_gen_output()` to parse results
5. Calls `assign_hydraulic_properties()` to compute k, b, T per fracture

### Step 3: (Optional) Generate summary report

```python
DFN.output_report()  # Generates PDF with network statistics
```

## Verification

1. `params.txt` exists in job directory
2. `dfngen_logfile.txt` shows no ERROR messages
3. Number of accepted fractures matches expectations:
   - If stopCondition=0: should equal nPoly
   - If stopCondition=1: p32 targets should be met
4. Radii in `radii_All.dat` are within [min_radius, max_radius] for each family
5. Network has connected paths between boundary faces (check log for connectivity info)

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| DFNGen version mismatch | Exit with version error | Recompile: `cd DFNGen && make` | dt_009 |
| Missing dfnworks_PATH | Exit with path error | Set `~/.dfnworksrc` | dt_010 |
| p32 target unreachable | Hangs or very long runtime | Reduce p32 or increase domain/max_radius | dt_011 |
| No connectivity | params.txt exists but no flow paths | Check boundaryFaces, increase p32 | dt_006 |
| Seed=0 gives different results each run | Non-reproducible networks | Set seed > 0 for reproducibility | — |

## Example

```python
from pydfnworks import *
import os

jobname = os.path.join(os.getcwd(), "output")
DFN = DFNWORKS(jobname, ncpu=4)

DFN.params['domainSize']['value'] = [10, 10, 10]
DFN.params['h']['value'] = 0.1
DFN.params['stopCondition']['value'] = 0
DFN.params['nPoly']['value'] = 50
DFN.params['seed']['value'] = 42
DFN.params['boundaryFaces']['value'] = [0, 0, 1, 1, 0, 0]

DFN.add_fracture_family(
    shape="rect", distribution="exp",
    kappa=10, probability=1,
    exp_mean=2.0, min_radius=0.5, max_radius=5.0,
    theta=0, phi=0,
    hy_variable='permeability',
    hy_function='constant',
    hy_params={"mu": 1e-12})

DFN.make_working_directory(delete=True)
DFN.check_input()
DFN.create_network()

# Verify: check that params.txt was created
assert os.path.isfile(os.path.join(jobname, "params.txt")), "Network generation failed"
print(f"Network generated with {DFN.num_frac} fractures")
```
