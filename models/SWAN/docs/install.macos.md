# SWAN macOS arm64 installation

## Native solver

The official Delft SWAN download page (https://swanmodel.sourceforge.io/download/download.htm) explicitly provides macOS arm64 41.51 binaries. Use the exact archive and SHA-256 in kiss.macos.arm64.yaml. Preserve the extracted SWAN-41.51-macOS-Silicon directory inside `<workspace>/binaries/SWAN`; the real native product is `SWAN-41.51-macOS-Silicon/bin/swan.exe` (Mach-O arm64), not its shell launcher and not the Python companion. The local audit on 2026-09-08 verified loading with Homebrew GCC libraries: libgfortran.5, libgomp.1 and libquadmath.0 under `/opt/homebrew/opt/gcc/lib/gcc/current`.

Invoking this official binary with `--version` in an empty directory and stdin closed exits zero with no stdout. It writes its genuine `swaninit`, `PRINT`, and `Errfile`; the latter two report `Terminating error: Input file missing`. This is a startup-only observation, not successful scientific execution. Do not fabricate INPUT or download test cases to make an installation check pass. The observed version comes from official release provenance; the program does not emit a version banner for this argument.

## Python companion required by this KI

The DAG's openearth/swan URL is the spectral I/O companion, not the Fortran solver. Clone https://github.com/openearth/swan.git at `c74c6cc0cd01307551106ee7bbe7d83e33f37c5d` into a separate workspace source directory. Do not use the unrelated PyPI `pyswan` distribution. At this exact upstream revision, repair Python package-relative imports before building its genuine wheel:

- In `pyswan/__init__.py`, change `import swan` to `from . import swan` and `import oceanwaves` to `from . import oceanwaves`.
- In `pyswan/swan.py`, change the actual import statement `import oceanwaves as ow` to `from . import oceanwaves as ow` (leave the docstring example alone).

These changes only repair packaging. Install that source with the workspace venv's `python -m pip install <source-directory>` after real numpy, scipy, matplotlib dependencies. Verify actual imports of `numpy`, `scipy`, `pyswan`, `pyswan.swan`, and `pyswan.oceanwaves`. Preserve the venv launcher in kiss.toml; never declare it as the SWAN binary. Bundled ki_tools_common comes from GeoForge, not an unrelated package.

The Windows record's previous Python-interpreter-only success does not establish a native solver installation. This Mac recipe explicitly supplies both genuine products and retains independent native/import verification. Full DS retry remains pending.
