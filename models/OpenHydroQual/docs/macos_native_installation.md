# macOS native installation: explicit version correction

The original KI labels OpenHydroQual 2.0.4 but declares an OHQLibTest executable
that is absent from the v2.0.4 source tree. This native installation uses official
v2.0.7, commit e24ea5eebcc0d2894b779adfdfc7ea78bd9a4ce2, and pinned jsoncpp
ca98c98457b1163cca1f7d8db62827c115fec6d1. The scientific reference description
still originates with the 2.0.4 KI; no cross-version scientific equivalence has
been established.

Build OHQLib (the real Aquifolium simulation engine) and its official OHQLibTest
command-line executable, using the platform manifest. Required native software:
Qt6 Core (validated 6.11.2), Armadillo headers (15.6.0), GSL (2.8), Apple BLAS/LAPACK
or the genuine CMake-detected equivalent, and libomp. Compile with two jobs.

The hash-guarded prepare_openhydroqual_build.py only adapts platform/build/CLI
integration for this exact source: the old Intel Homebrew libomp path, Windows
DLL import declarations and macro, Armadillo's supported ARMA_DONT_USE_WRAPPER
configuration using genuine BLAS/LAPACK, explicit CLI OpenMP dependency, resource
path relative to the actual build layout, and bounded --help/--version handling.
It does not alter the numerical model or create a substitute implementation.

Armadillo's optional shared wrapper pulled a Homebrew ARPACK dependency referencing
a missing OpenMPI dylib on this host. The supported header-only mode avoids that
unused wrapper dependency. No MPI system links are changed. Native compiler/linker
verification must succeed; never satisfy missing libraries with symlinks to an
incompatible implementation.

Upstream OHQLibTest treats any supplied argument as a script, then calls Solve.
The new early-exit help/version branches precede System/Script construction.
Probe only the patched executable with --help or --version from an empty directory.
Do not run model files, input datasets, or scientific preflight during installation.
Retain source resources/main_components.json and resources/settings.json, which
are genuine distributed software templates, rather than fabricating replacements.

The local compiler reported real upstream infinite recursion in Matrix_arma.cpp
compound arithmetic operators. Those numerical sources remain unchanged. Passing
compilation/load/CLI checks demonstrates installation only; it does not establish
scientific correctness or endorse executing affected arithmetic paths.
