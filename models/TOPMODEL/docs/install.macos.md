# TOPMODEL native macOS installation

Adapt the retained Windows manifest's exact source pin `7e193d3fb3d94ffec448b04bcbe0b5d01c53bb36` from NOAA-OWP/topmodel. This is the 2021 BMI implementation declared by this KI. Windows used `make -C src clean`, `make -C src`, producing `run_bmi`. Its recorded installation result does not establish a Mac pass.

From the checkout at `binaries/TOPMODEL`:

```sh
python3 ../../ki/tools/prepare_topmodel_build.py .
make -C src clean
make -C src -j2
```

The Apple command-line tools supply the compatible C compiler; only the system C library is linked on Apple Silicon. The native product stays at `binaries/TOPMODEL/run_bmi`, matching the manifest and preflight. No external model runtime configuration is needed.

The upstream driver is `main(void)`, ignores arguments and initializes BMI using `./data/topmod.run`. The pinned helper changes only `src/main.c`: genuine native `--help`/`--version` branches return before allocation/BMI initialization, unrecognized arguments return2, and absence of the required configuration produces a clear error before model initialization. Existing no-argument execution with readable case configuration follows the original model path. Numerical source `topmodel.c`, `bmi_topmodel.c` and headers are unchanged. The helper checks the exact source commit and original/patched main.c hashes and is idempotent.

The earlier Mac attempt selected newer `366a975`, which differs substantially in model source from the Windows/declared2021 implementation. Its agent separately reported an empty-directory SIGSEGV; the retained independent verdict was missing the binary at its declared path. Neither counts as successful startup. Do not repeat that source substitution or incorrect output placement.

Local native proof: Mach-O ARM64 run_bmi, 69,992 bytes, SHA-256 `7d927b46f69891cc3e074358a3229532afefbc1c0922fd980dd9f126e0220548`; only `/usr/lib/libSystem.B.dylib` linked. Independent `--help` and `--version` probes returned0 in empty directories. An empty-directory no-argument check returned2 with the expected missing-configuration message. All three created no files. These are native installation facts, not hydrological validation or a DS pass.

Use only help/version for installation. Never run the bare model in its bundled source/example directory, because that can execute the scientific model. Python authoring/preprocessing dependencies are separate: numpy, pandas, PyYAML, compatible GDAL bindings, and the real bundled ki_tools_common where required by tool imports. Match GDAL's Python binding version to the installed libgdal; do not replace workspace ki_tools_common with an unrelated package.
