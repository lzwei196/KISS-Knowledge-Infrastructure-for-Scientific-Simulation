# Native FATES installation on Apple Silicon

FATES is a hosted component. This installation pins CTSM ctsm5.4.054 (`dae706a769a04ff13def0a909930c899a265368a`) and the matching FATES `sci.1.92.7_api.46.0.0` gitlink (`121723f64e94be97fd91fc95cfd1ba72dfc191ee`). CIME is 6.5.5 at `92ae0fd8133a3397a95f1cfcfa40dc138562f305`; ccs_config is `7c8bd604c818e4e832dda02b8584260fb7e22efc`. Do not replace this compatibility set with latest master.

From `binaries/FATES` run:

```sh
python3 ../../ki/tools/build_fates_native.py . --runtime /absolute/native-runtime --python /absolute/python3.11
```

Or supply workspace-root `fates-build-config.json` containing `native_runtime` and `build_python` absolute path values. Validated configuration is persisted inside the source root. The runtime requires genuine ESMF/NUOPC, PIO, MPICH and netCDF C/Fortran development libraries and matching Fortran modules. The audited stack is ESMF 8.9.1, PIO 2.6.9, MPICH 5.0.1, netCDF C 4.10.1, netCDF Fortran 4.6.3, GNU Fortran 16.2.0 and Python 3.11. No shim or ABI alias libraries are used.

The helper creates official `I2000Clm50FatesRsGs` at `f19_g17` with one MPI task and two compile jobs. The case's expanded compset contains `CLM50%FATES`; CIME selects `CLM_BLDNML_OPTS=--bgc fates`. The grid is allowed for this build-only configuration through CIME's `--run-unsupported` option; that does not establish scientific support for a simulation.

Output and prospective input roots stay inside the workspace. The helper performs software setup and two native build stages: support libraries with `lnd` explicitly selected, then model-only component compilation and native linking. CIME build selection suppresses namelist generation. It never downloads inputdata, generates scientific namelists, submits a case or runs a simulation. FATES's shipped JSON parameter file is software source; it is not necessary to convert parameters or prepare scientific forcing for this installation.

The native product is `ki-fates-build/cesm.exe`; CIME scripts, Python imports and the FATES source checkout do not satisfy this target. Runtime parameter activation and demographic science validation require a later scientific run, which this installation check does not perform.

The upstream executable has no help CLI. Probe `--help` only in an empty temporary directory with a bounded timeout. The exact pinned CMEPS driver reads `drv_in` at `components/cmeps/cesm/driver/esmApp.F90:54` before model initialization. A return code of 2 with `Fortran runtime error: Cannot open file 'drv_in': No such file or directory` is the narrowly source-verified native startup boundary. Arbitrary failures or missing dynamic libraries are not success. The audit uses `FI_PROVIDER=tcp` and `FI_TCP_IFACE=en0` for local MPICH startup.

Local native proof: the linked ARM64 executable is 15,252,456 bytes, SHA-256 `47b10be76a0344b5bc2ffbd2604e43760f5a70e2c5bfbd183389bb09416e53ea`. It contains 1,482 FATES symbols and 37 Fates-named native objects were built. Independent empty-directory startup returned the exact code-2 missing-drv_in boundary and created no files. Scientific input directory remained empty. This is local compile/link/load evidence; a fresh DS installation result must be recorded separately.
