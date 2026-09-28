# Native icepack installation on Apple Silicon

The KI targets the genuine icepack glacier library 1.1.0 at commit
`6c67b51b445398cf4a6ef284ebe602c397bd6ee4`, not another package named icepack.
There is no 1.1 tag. The pinned source declares 1.1.0.

Run `python3 ../../ki/tools/build_icepack_native.py .` from `binaries/icepack`.
The existing workspace `icepack-build-config.json` supplies `python` (the workspace
Python3.11 venv launcher), `native_wheel_dir`, `petsc_dir`, and `petsc_arch`.
Absolute dependency prefixes are on this same Mac; call the trusted helper before
assuming they are missing or requesting user intervention. Preserve `kiss.python`
as the venv launcher without resolving its symlink to the base interpreter.

The helper verifies the original source and native wheel SHA256 receipts, installs
actual compiled dependencies, installs icepack from the newly acquired source,
and verifies every installed icepack Python source file against that pin. It then
imports the native stack in an empty directory: Firedrake2026.4.2, PETSc3.25.5,
MPICH4.3.1, MPI-enabled h5py3.16.0, and native ROL/pyroltrilinos0.5.6. No scientific
model call or dataset is needed. An interpreter alone does not establish success.

These same-host dependency wheels were built from genuine sources with native
Apple Silicon compilers. PETSc3.25.5 uses its own MPI-enabled HDF5 1.14.6 and
NetCDF libraries. h5py and Firedrake must link that HDF5: the base conda Python's
serial HDF5 is incompatible. The audited rebuild used `LDSHARED` and `LDFLAGS`
with the PETSc architecture library directory first. No ABI symlink substitutions
are used. Native wheels retain their absolute library providers and must not be
moved to another Mac without rebuilding and verifying the dependencies there.

The actual cold full import passed in 65.27 seconds with no output files. Import
checks have a 180-second bound; a timeout is failure. Never run `firedrake-check`,
scientific tests, solvers, mesh generation, datasets, or notebooks for installation.
This establishes installation and linking only, not numerical validation.

Sources: https://www.firedrakeproject.org/install.html and
https://github.com/icepack/icepack/tree/6c67b51b445398cf4a6ef284ebe602c397bd6ee4 .
