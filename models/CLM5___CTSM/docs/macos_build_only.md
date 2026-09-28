# Native macOS build-only installation

Use the manifest and bundled `tools/build_ctsm_native.py`. The authoritative
model is CTSM ctsm5.4.054 at dae706a769a04ff13def0a909930c899a265368a, with CIME
92ae0fd8133a3397a95f1cfcfa40dc138562f305, ccs_config
7c8bd604c818e4e832dda02b8584260fb7e22efc, and FATES
121723f64e94be97fd91fc95cfd1ba72dfc191ee (sci.1.92.7_api.46.0.0).
The required native product is binaries/CTSM/ki-build/cesm.exe. A CIME Python
import or create_newcase script is not the scientific model executable.
Legacy CESM2.2.2 instructions describe a different historical route.

From binaries/CTSM, run:

```
python3 ../../ki/tools/build_ctsm_native.py . --runtime /absolute/native/prefix --python /absolute/python3.11/launcher
```

Use real paths, never the placeholder strings above. Alternatively preseed the
installation workspace's ctsm-build-config.json with absolute `native_runtime`
and `build_python` paths. The helper also accepts CTSM_NATIVE_RUNTIME and
CTSM_BUILD_PYTHON when the calling environment preserves them. It validates real
esmf.mk, esmf.mod, netcdf.mod, MPI wrappers and libpioc, then persists the validated
configuration in the source checkout for later repairs. The audit provisioned
ESMF8.9.1, PIO2.6.9, MPICH5.0.1 and netCDF in a genuine conda runtime and verified
a native Fortran ESMF/MPI initialization plus netCDF library call using host
GNU Fortran. Python3.11 is a real existing interpreter, never an imp module shim.

The helper checks source pins, populates official software submodules through
git-fleximod, and adapts the upstream homebrew Darwin machine to the runtime
prefix and workspace-local output paths. It creates one-task I2000Clm50SpRsGs
and performs case.setup. It then calls the official CIME case_build API in two
stages, both of which suppress scientific namelist generation:

1. sharedlib_only=True with the case's actual CASE_SUPPORT_LIBRARIES plus `lnd`.
   Pinned CIME build.py:884 treats CLM itself as a shared component; omitting lnd
   leaves libclm.a absent. CDEPS/csm_share are required names missing from the
   narrower command-line --build choices.
2. model_only=True, buildlist=None. This compiles the remaining native components
   and links cesm.exe. A nonempty buildlist would prevent this driver's final link.

No CIME engine source or verification gate is patched. Each helper command
retains a ctsm-build-step-N.log and prints its actual failure tail. Diagnose the
first real compiler/linker error rather than interpreting truncated outer Python
tracebacks as missing dependencies or permission problems. Rebuild a failed
component using CIME's own clean/build controls when appropriate.

Do not call case.submit, case.run, scientific preflight, or input-data download
commands. Do not execute model cases. Probe the native executable only from an
empty directory with bounded runtime. The pinned CMEPS esmApp.F90 opens the
case namelist drv_in before model initialization; retain actual startup output
and distinguish a source-confirmed missing case input from a crash or missing
native library. No scientific correctness or cross-physics equivalence is
established by compilation/load checks.
