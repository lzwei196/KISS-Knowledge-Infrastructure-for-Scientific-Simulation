# Native macOS installation

The audited product is PISM v2.3.0, official commit `79cae578d27cf90742be04c0c5a8bcf262da41ca`, built as a native arm64 executable. `pism -version` completed successfully in an empty directory and reported PISM, PETSc, MPICH, NetCDF, FFTW and GSL versions. It created no files and did not load scientific inputs. The double-dash `--version` flag is unsupported.

Use the workspace's genuine Python 3.11 environment for `tools/build_pism_macos.py`. PETSc 3.21.4 still uses Python's `xdrlib`; do not fabricate a replacement module. Install the required KI imports, NumPy and netCDF4, into that environment.

Prepare `binaries/PISM/deps/runtime` using a genuine micromamba environment created from `tools/macos-dependencies.explicit.txt`. This file pins the audited native FFTW 3.3.11, UDUNITS 2.2.28 and dependencies by official conda-forge package URL and digest. Keep this prefix inside the installation workspace. Existing host dependencies are MPICH 4.3.1, GSL 2.8, NetCDF-C 4.10.0, CMake, and native compilers. No shared package installation or compiler changes are performed by the helper.

From the installation workspace, run:

```text
venv/bin/python ki/tools/build_pism_macos.py
```

The helper validates the official PISM source pin, downloads and SHA256-checks PETSc 3.21.4, configures it with the same MPICH ABI, builds PETSc, and builds only PISM's `pism` target. PETSc's optional HDF5 backend is disabled. The retained PFLOTRAN PETSc/HDF5 stack cannot be reused directly: its HDF5 lacks zlib, and linking it alongside host NetCDF would introduce a second HDF5 library stack. PISM retains NetCDF support through the host NetCDF library.

The genuine upstream build generates `pism_config.nc` from its distributed configuration CDL. The helper copies those unchanged bytes to the compiled-in `runtime/share/pism` directory. This is a runtime configuration resource, not a scientific case. Keep the source build's executable/shared library and the configured runtime/dependency prefixes together; this build is not a relocatable binary package. No examples, calibration, verification models, or simulations are run.

The audited configuration excludes optional Python bindings, PROJ, YAC, and parallel NetCDF backends. The caller can supply verified `FI_PROVIDER=tcp` and `FI_TCP_IFACE=en0` settings on the audited host where MPICH needs explicit interface selection. These settings do not replace MPI.

After building, run the exact `pism -version` probe and independent installation verification. Do not satisfy an installation check by creating a scientific input file. Local native proof is complete; an end-to-end DS attempt remains pending.

Sources: [official PISM source](https://github.com/pism/pism/tree/79cae578d27cf90742be04c0c5a8bcf262da41ca), [PISM prerequisites](https://www.pism.io/docs/installation/prerequisites.html), [PETSc 3.21.4 source](https://web.cels.anl.gov/projects/petsc/download/release-snapshots/petsc-3.21.4.tar.gz).
