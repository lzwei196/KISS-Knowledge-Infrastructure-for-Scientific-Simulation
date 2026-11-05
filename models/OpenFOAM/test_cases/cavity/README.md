# OpenFOAM — foundation test case: "cavity"

Authentic foundation case: the official **lid-driven cavity** tutorial that ships with
OpenFOAM (`tutorials/incompressibleFluid/cavity`). A 0.1 m square box of fluid, the top
wall (lid) slides at 1 m/s, the other walls are fixed. This version of the tutorial uses
the k-epsilon turbulence model (nu = 1e-5 m2/s, so Re = 10 000) and runs 10 s of flow.
`inputs/` are the unmodified files from the OpenFOAM git tree (`git show HEAD:`).

| | |
|---|---|
| Engine | OpenFOAM-dev (OpenFOAM Foundation), build `dev-d41922f7f4a1`, `blockMesh` + `foamRun` (solver module `incompressibleFluid`) |
| Source | github.com/OpenFOAM/OpenFOAM-dev, `tutorials/incompressibleFluid/cavity`, commit d41922f7 |
| Licence | GPL-3.0-or-later (OpenFOAM Foundation) |
| KI | `OpenFOAM` |
| Size / time | 13 small text files (~13 KB); 400 cells, 2000 steps, about 2 s on 1 core |

## Run
```
python run_reference.py    # 0=PASS 2=FAIL 3=OpenFOAM missing
python run_reference.py --foam-bashrc /path/to/OpenFOAM/etc/bashrc
```
OpenFOAM is found from `--foam-bashrc`, then `$OPENFOAM_BASHRC`, then an already-sourced
`$WM_PROJECT_DIR`, then `which foamRun`, then the server default build.
The script copies `inputs/` to a fresh temp dir and does what OpenFOAM's own
`bin/foamRunTutorials` does for a tutorial with no `Allrun`: `blockMesh`, then `foamRun`.
`foamRun` is run through the KI's own `tools/run_openfoam.py`; the result fields are
read with the KI's own `tools/parse_openfoam_output.py`. The temp dir is deleted after.

## Expected (recorded 2026-10-05; deterministic: two clean runs gave byte-identical output)
No reference output ships with this tutorial, so the values come from our own real runs.
(The well-known Ghia et al. 1982 data is for laminar Re=100 on fine grids and is not part
of OpenFOAM, so it is not used.)
- both `blockMesh` and `foamRun` finish with OpenFOAM's normal `End` line, return code 0
- 21 time folders (0 to 10 s every 0.5 s); 400 cells
- at t = 10 s: mean speed 0.10514 m/s, max speed 0.2513 m/s;
  kinematic pressure mean -0.008777, min -0.01686, max 0.03562 m2/s2;
  k mean 6.730e-4, k max 1.959e-3; epsilon mean 1.113e-3; nut mean 4.899e-5
- max Courant number 0.2518; all final residuals < 1e-3

Tolerances in `expected.json` are wider than the exact repeat so that another build of
OpenFOAM still passes, but much smaller than any real change in the flow.

## KI gaps (status 2026-10-06)

No KI tool fix for OpenFOAM has landed in this checkout since the case was made (last OpenFOAM commit `50ac142`), so every item below is still open.

- **Still open:** No KI tool runs `blockMesh` on the case's own `blockMeshDict`. `tools/generate_mesh.py`
  always writes a new `blockMeshDict` from its own arguments, which would replace the
  official one. So `run_reference.py` runs `blockMesh` directly (with the same bashrc).
- **Still open:** `tools/run_openfoam.py` keeps only the last 2000 characters of the solver output and
  writes no `log.foamRun`, so the full residual history cannot be read afterwards with
  `tools/parse_openfoam_output.py --extract-residuals`.
- **Still open:** `tools/run_openfoam.py` lists output time folders in text order ("10" before "2").
