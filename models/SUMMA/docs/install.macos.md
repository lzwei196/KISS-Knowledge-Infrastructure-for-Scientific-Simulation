# SUMMA: Mac installation guidance

Learned from windows-version fbed40b08f2d7c552c5c332a912b5a65f3d8855c on 2026-09-08. This is unverified Mac guidance, not a Mac installation result.

Official source: https://github.com/CH-Earth/summa.git
Windows recipe source ref: `2213bc57358e6709b48217cfce64f96a4b90b287`

The pinned v3.0.0 source matches the KI file-manager configuration era. Supply the upstream build/Makefile with a consistent native Fortran compiler and real netCDF-C/netCDF-Fortran plus their required HDF5/zlib and BLAS/LAPACK dependencies. Learn F_MASTER, FC, FC_EXE, INCLUDES and LIBRARIES from the Windows configuration, resolving them to Mac prefixes. Windows compiler-specific patches are not Mac evidence.

Keep installation within the selected workspace. Verify the actual native product and required package imports. Preserve explicit blockers and installation evidence.
