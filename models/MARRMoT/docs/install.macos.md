# MARRMoT macOS installation

The actual product is the official MARRMoT 2.1.2 MATLAB/Octave toolbox, pinned at a95b925669385e6c747637dec45c848601177ea4. All 47 model classes have been loaded locally using native ARM64 Octave 10.3.0, with exact class metadata, all 48 original source SHA256 values from the manifest, source paths and model_fun methods checked. The native optim module also loaded. No model object was constructed and no model timestep, calibration, example, forcing data or scientific dataset was used. DS end-to-end testing remains required.

This adapts Windows source/dependency configuration. The Windows portable Octave archive and mingw64 executable paths do not apply to Mac. Source presence or octave --version alone cannot establish an installation pass.

Use a genuine native osx-arm64 Octave 10.3.0 installation at <workspace>/binaries/octave. An isolated conda-forge environment was verified locally; do not modify the system MPI/compiler stack as part of this recipe. The setup environment must set OCTAVE_HOME and OCTAVE_EXEC_HOME to that runtime prefix, exactly as the conda package's supplied activation script does. Without OCTAVE_HOME, direct CLI invocation can recurse through a wrong image directory and crash during startup.

Install packages into <workspace>/octave_packages/packages with local registry <workspace>/octave_packages/package-list and a scoped empty global registry. Verified source packages:

- optim 1.6.3, SHA256: 59fb3771a2d2a2313447532c59a2e000a6a7bb7a677f3ef8183fbaaab5493a14
- statistics 1.7.7, SHA256: cef3c090aee13eaad50b4b9beb2f003e8756cbf018d2be7233326de9696cdf7e
- struct 1.0.18, SHA256: fccea7dd84c1104ed3babb47a28f05e0012a89c284f39ab094090450915294ce

Package source and dependency details are published at https://gnu-octave.github.io/packages/optim/ , https://gnu-octave.github.io/packages/statistics/ and https://gnu-octave.github.io/packages/struct/ . Current statistics releases requiring Octave 11 must not be selected for this Octave 10 recipe.

Package build adaptations verified locally: query mkoctfile's documented configurable compiler flags, remove NUL padding left by conda prefix relocation, use C++17 with Apple Clang, use -Xpreprocessor -fopenmp, and separate normal configure-executable LDFLAGS from .oct shared-bundle ALL_LDFLAGS/DL_LDFLAGS. Preserve the genuine compiler/runtime libraries. This fixes installation configuration, without patching model equations or suppressing compilation failures.

When copying prepared package directories to a new workspace, the package-list contains absolute paths. Re-register the copied packages using scoped pkg prefix/local_list/global_list followed by pkg rebuild -local; never leave the old absolute registry unchanged. The independent checker rejects package modules loaded outside the current workspace.

The supported fixed installation probe is tools/load_marrmot_installation.m. Invoke the native CLI with --no-init-all --no-history --no-window-system --quiet, followed by that exact script and arguments: the absolute pinned repository root, absolute octave_packages root, comma-separated 47 class names from the manifest, and optim=1.6.3,statistics=1.7.7,struct=1.0.18. The engine additionally checks all 48 original source hashes and actual native module type. Arbitrary Octave scripts, evaluation, constructors and scientific model calls are outside this installation probe.

Upstream original comments contain some non-UTF8 bytes. Octave emits comment-decoding warnings while loading these class definitions; the original source files were preserved and all 47 classes loaded successfully.
