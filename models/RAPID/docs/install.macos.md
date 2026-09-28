# RAPID: Mac installation guidance

Learned from windows-version fbed40b08f2d7c552c5c332a912b5a65f3d8855c on 2026-09-08. This is unverified Mac guidance, not a Mac installation result.

Official source: https://github.com/c-h-david/rapid.git
Windows recipe source ref: `83145101ac8b49b8269e330cfc1372876fce8d7d`

Use the pinned official Fortran/PETSc implementation and its upstream make target in src. Supply real native PETSc and the dependencies declared by that pinned makefile. The portable MSYS2/MinGW route is Windows-only. A wrapper or Python substitute is not the RAPID executable.

Keep installation within the selected workspace. Verify the actual native product and required package imports. Preserve explicit blockers and installation evidence.

## Deterministic native dependency route

Retry 40 built the real RAPID 20240624 executable but reached the driver deadline before the independent installation receipt. Retry 49 spent its budget rebuilding netCDF even though this Mac already supplies the genuine native NetCDF-Fortran 4.6.2 and NetCDF-C libraries. Use their full NetCDF4-capable build; do not replace it with classic-only NetCDF to simplify a startup check.

The bundled `tools/build_rapid_macos.py` builds the SHA256-pinned official PETSc 3.13.6 archive against existing `/opt/homebrew/opt/mpich` and native BLAS/LAPACK, then builds the pinned RAPID source using the real `nf-config --fflags`, `--flibs`, and `nc-config --libs`. It keeps PETSc under the selected workspace and leaves the actual `src/rapid` executable at the manifest product path. Invoke it with the workspace's genuine Python 3.11 venv, from the installation workspace. The helper needs an already acquired clean RAPID source checkout at the manifest commit. Example: `venv/bin/python ki/tools/build_rapid_macos.py` (adjust the KI helper path to its real location).

Configure and build PETSc with two jobs; use explicit `make -j1 rapid` because RAPID's upstream makefile races Fortran `.mod` outputs under parallel make. Python 3.11 supplies genuine `xdrlib` and `distutils`; do not generate a substitute module. No `--download-mpich`, `--download-fblaslapack`, or fresh netCDF build is needed for this host route. PETSc 3.25 is not interchangeable with RAPID's legacy PETSc Fortran interfaces.

On the audited host, MPICH's libfabric initialization needs inherited `FI_PROVIDER=tcp` and `FI_TCP_IFACE=en0`. These name a verified real interface; another Mac must select its actual working interface. The helper preserves those caller settings and does not alter global libraries or compiler links. Installation verification runs `src/rapid --version` from an empty directory with closed stdin. The source handles this option before case namelist loading, so it requires no scientific inputs and runs no simulation.

Local native audit completed with genuine PETSc 3.13.6 and a Mach-O arm64 RAPID product printing `RAPID: 20240624`, exit 0 in 1.5 seconds. The initial link exposed that `nf-config --flibs` omitted NetCDF-C's library search directory; adding the real `nc-config --libs` fixed it. The configured OpenBLAS search prefix resolved `-llapack -lblas` to macOS Accelerate; `otool -L` confirmed these actual framework libraries. This is native host BLAS, not a bundled OpenBLAS claim. Local build proof does not replace the independent DS installation receipt.
