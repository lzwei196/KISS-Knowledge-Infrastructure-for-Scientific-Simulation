# GIFMod 0.1.26 native macOS installation

The launcher has already provided a genuine Qt5 development prefix in the
workspace-root `gifmod-build-config.json`. Its absolute `qt_runtime` path is
on this SAME host and is intentionally outside the temporary install workspace;
it is not a stale path from another machine. The helper validates qmake and
Qt5.15.15 before compiling. Invoke that helper with the existing configuration
BEFORE attempting package installation or requesting user action. Do not infer
that the prefix is missing from `which qmake`: qmake need not be on PATH.
Do not replace the configuration merely because its path is external.

After the exact source checkout, from workspace root invoke
`python3 ki/tools/build_gifmod_native.py binaries/GIFMod`.
The manifest's equivalent relative command runs with cwd `binaries/GIFMod`.
The source belongs directly there, not an extra `source/repo` subdirectory.
If dependency validation fails, retain the exact helper error and diagnose it;
no missing-dependency claim is justified before this check.

Build USEPA/GIFMod commit `2a314750418099ca51a100d824381924ba982c91`.
`src/GUI/mainwindow.cpp` declares GIFMOD_VERSION 0.1.26. The repository has no
release tag for this pin. No corresponding retained Windows installer manifest
exists. The old bundled ELF executable cannot serve as a Mac installation.

The audited runtime is conda-forge `qt-main=5.15.15` for osx-arm64, with Apple
Clang, make, Homebrew libomp, and Accelerate. A genuine isolated prefix can be
provisioned with micromamba create -p PREFIX -c conda-forge qt-main=5.15.15.
Place `{"qt_runtime": "/absolute/path/to/prefix"}` in workspace-root
`gifmod-build-config.json` before installation. Qt remains at that prefix for
runtime linking. Do not replace it with Qt6. Upstream uses embedded Duktape,
not a missing QtScript module.

Clone the exact pin into binaries/GIFMod (a source-only sparse checkout of
`src` and `include`, plus root files, is sufficient). From that directory run:

```
python3 ../../ki/tools/build_gifmod_native.py .
```

The helper verifies source identity and hashes, applies the bundled patch,
invokes genuine Qt5 qmake and make -j2, and copies software GUI resources.
No scientific input archive or model run is needed. The actual product is
`builds/release/GIFMod`, a native Mach-O arm64 executable.

Reviewed changes affect only build and GUI/compiler integration: use native
libomp and Accelerate with bundled Armadillo headers; explicitly include
QPainterPath; correct legacy TeX-to-HTML formatting argument types and pointer
error returns; add --help/--version before QApplication. Model solver sources
are unchanged. Existing upstream GUI formatter warnings, including returning
a local buffer, remain; this installation proof does not validate GUI workflows
or scientific predictions.

Local full compilation produced 155 native objects and a 6,089,272-byte binary.
Both --help and --version exited 0 in empty directories, loaded actual Qt5 and
native libraries, and created no files. Fresh DS repair88 independently rebuilt and passed the native installation gate
on 2026-09-09 in 904.2 seconds: Mach-O identity, linking, Python imports and
exact --version output all passed with exit0 and no timeout. Repair86 remains
a retained failure caused by the agent mistaking the existing runtime for a
foreign-host path. The manifest now also excludes libomp from executable PATH
checks; it remains a real linked library dependency. A timeout or GUI launch
is not success.
