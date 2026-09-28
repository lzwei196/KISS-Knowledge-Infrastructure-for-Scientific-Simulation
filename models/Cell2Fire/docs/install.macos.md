# Native macOS installation

This recipe adapts Windows' official C2F-W product identity and Python dependency
contract to a source build using the project's own macOS makefile. The Windows
PE executable and DLLs cannot be reused as native Apple Silicon artifacts.

Source: https://github.com/fire2a/C2F-W/tree/83b0c3bc31fa9bd500ff11400671e48bdc98a237

Upstream `ReadArgs.cpp` prints a heading on `-h` but continues into data loading;
`--help` and `--version` are not recognized. The supplied SHA256-guarded source
helper adds early returns at the start of the genuine C++ main function. The
help lists existing CLI options; the version remains the genuine embedded
`C2FW_VERSION`. No numerical methods, data readers, or model behavior are changed
for scientific invocations. Never count an input-loading crash as a successful
installation probe.

The installation product is `Cell2Fire/Cell2Fire` relative to the source root.
Build with `make -C Cell2Fire -f makefile.macos -j2`; do not execute the tests or
example cases for this installation-only check. Preserve the isolated Python
launcher and import the required real KI dependencies.
