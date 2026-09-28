# Native macOS HRLDAS / Noah-MP v5.2.0 installation

Use the official `NCAR/hrldas` v5.2.0 driver pinned in the Mac manifest and
its matching pinned `NCAR/noahmp` submodule. The physics-only Noah-MP repo does
not provide a standalone driver executable by itself.

Before building, initialize the submodule and run the KI helper
`tools/prepare_hrldas_macos.py` from the installation workspace root with the
argument `binaries/Noah_MP/source/hrldas`. The helper refuses other source
revisions and writes native serial GNU Fortran / `nf-config` build options.
It changes only the three Noah-MP Makefiles, preserving model physics.

Default macOS APFS is case insensitive: upstream `Machine.F90` and generated
`Machine.f90` refer to the same file. Upstream preprocessing truncates the
source and `make clean` deletes it. This is deterministic filename collision,
not random filesystem corruption or evidence that GNU make 3.81 is broken.
The helper changes intermediates to `*.ki-preprocessed.f90`, keeps explicit
original object filenames, and scopes cleanup to these distinct intermediates.
Never run the original unpatched `make clean` on this checkout.

Run these ordered commands relative to the HRLDAS checkout; serial make is
intentional because the upstream cross-directory Fortran module dependency
order is incomplete:

```sh
make -j1 -C hrldas/Utility_routines
make -j1 -C noahmp/utility
make -j1 -C noahmp/drivers/hrldas NoahmpIOVarType.o
make -j1 -C noahmp/src
make -j1 -C noahmp/drivers/hrldas
make -j1 -C urban/wrf
make -j1 -C hrldas/IO_code
make -j1 -C hrldas/run
```

These targets build the complete native driver. The top-level default also builds
optional GRIB forcing conversion utilities requiring Jasper, which are outside
this installation contract; do not build those utilities or fetch datasets.

The product is `hrldas/run/hrldas.exe`. Preserve the source tree, distributed
parameter tables, and the binary. An installation-only startup probe uses an
empty directory, no stdin, and a bounded timeout. Do not create a namelist,
fetch forcing/setup datasets, invoke the KI simulation wrapper, or launch a
scientific case to demonstrate installation. Record the actual native startup
and required Python imports independently.
