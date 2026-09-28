# Native dfnWorks 2.10 installation

The KI's declared version is official dfnWorks2.10.0 at commit
1c102b068097a9b9d8bfa9182dd6d2d2d41cf6c8, including DFNGen2.3. Current upstream
master is newer and must not replace that pin. Installation means the actual
native DFNGen, DFNTrans, volume correction and mesh connectivity tools, actual
pydfnworks2.10.0, LaGriT3.3.3 and an explicit verified PFLOTRAN/PETSc dependency.
The Python interpreter alone is insufficient.

Run the following from the installation workspace with its genuine Python3.13
venv and native Apple clang plus Homebrew gfortran/CMake available:

```
venv/bin/python ki/tools/build_dfnworks_macos.py
venv/bin/python ki/tools/verify_dfnworks_native.py
```

The helper retrieves source-only sparse checkouts of dfnWorks and official
LaGriT V3.3.3 commit35f2fc81ae0b42a00f05e332db9f762516dc51fd. Original tracked
source must remain clean and patch inputs must match bundled hashes. Separate
build copies receive the documented native CLI patches. Two jobs are used.
The genuine package is installed from its original pinned pydfnworks source.

The explicit workspace `dfnworks-build-config.json` requires `pflotran_exe`,
`petsc_dir`, and `petsc_arch`. This audit reuses an existing verified official
PFLOTRAN commitfab315dc6559306f2f93b27571bf5add812dd820 with PETSc3.21.4 and
parallel HDF5. Its absolute linked prefix must remain in place; it is not a
relocatable binary. Fixed verification checks the exact executable SHA256,
source pin, native library paths and PETSc startup. This shared dependency is
reported separately from the fresh dfnWorks/LaGriT builds.

The helper writes `binaries/dfnWorks/runtime-paths.json`. The Mac KI runner assigns
this path to upstream `pydfnworks.general.paths.DFNPARAMS` before the existing
model calls. Set `DFNWORKS_RUNTIME_PATHS` explicitly when running from elsewhere.
No HOME file is created. This also avoids an upstream fallback defect where
None-valued environment defaults do not read exported variables. Installation
validation checks only this assignment, never constructs a model.

Native CLI modifications:

- DFNGen gains early `--version` using constants parsed from upstream
  pydfnworks.__version__ and makefile DFNGEN_VERSION. It prints
  `dfnWorks 2.10.0 DFNGen 2.3`, exits0 before generation, and creates only the
  upstream global logger's empty dfngen_logfile.txt. Model equations are unchanged.
- LaGriT gains early `--version` using its generated upstream version parameters.
  It prints `LaGriT 3.3.3`, exits0 before initialization, and creates no files.
- DFNTrans, correct_volume and ConnectivityTest retain original source. Their
  fixed no-argument checks exit1 at documented missing-input boundaries before
  any scientific input is read. Do not pass --version to these utilities.

Modern compiler accommodations: DFNTrans uses `-include sys/stat.h` and
`-Wno-error=return-mismatch` for an upstream void function's return1 warning;
LaGriT uses `-fallow-argument-mismatch` and clang legacy implicit-int/function
warnings. These flags retain source numerics; no scientific execution was tested.

Upstream2.10 requires LaGriT3.3 for DFN meshing. Its optional DFM matrix meshing
requires Exodus, which this build excludes. FEHM is also excluded. The installed
full DFN path uses LaGriT, PFLOTRAN and DFNTrans; no claim is made for these optional
capabilities or scientific accuracy. Do not create mesh/forcing/case inputs,
construct DFNWORKS, or run examples to pass installation.

The root-owned independent audit must retain `dfnworks-native-dependencies.json`
for all six native products and actual package load before counting DS success.
A successful primary DFNGen engine probe alone does not establish full readiness.

- https://github.com/lanl/dfnWorks/tree/1c102b068097a9b9d8bfa9182dd6d2d2d41cf6c8
- https://github.com/lanl/LaGriT/tree/35f2fc81ae0b42a00f05e332db9f762516dc51fd
- https://github.com/lanl/dfnWorks/blob/1c102b068097a9b9d8bfa9182dd6d2d2d41cf6c8/README.md
