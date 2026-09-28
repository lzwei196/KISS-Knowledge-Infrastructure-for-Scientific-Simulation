# ELM native installation on Apple Silicon

Build the actual coupled E3SM v3.0.0 executable at commit `399d4301138617088dd93214123d6c025e061302`. The official `mac` machine supports GNU and MPICH. No scientific inputs are needed for this compile/link route. Scientific validation remains separate.

From the workspace's `binaries/ELM` checkout, run:

```sh
python3 ../../ki/tools/build_elm_native.py . --runtime /absolute/native-runtime --python /absolute/python3.11
```

Alternatively put `elm-build-config.json` in the workspace root (or source root) with `native_runtime` and `build_python` absolute path values. This avoids relying on inherited environment variables. The helper persists validated configuration in the source root.

The native runtime must contain genuine MPICH, netCDF C/Fortran and PnetCDF development headers, modules and libraries. The audited native stack used MPICH 5.0.1, netCDF C 4.10.1, netCDF Fortran 4.6.3, Apple Clang and GNU Fortran 16.2.0. Python 3.11 runs this pinned CIME. Use actual compiler/MPI modules; configuration checks alone do not establish compatibility.

The helper acquires exact gitlinked CIME, MCT, SCORPIO, EKAT, FATES, MPP and BeTR software sources. It creates an I1850ELM/f19_g16 case with one MPI task and two build jobs, using workspace-local case, build, run and input roots. CIME's namelist-generation option is disabled after Case construction, since Case resets configuration. ELM's own `bld/configure` creates compile metadata. Empty coupler/MOSART metadata directories are created directly. No component buildnml, check_input_data, case.run or case.submit is invoked.

The native support stages compile GPTL, MCT, SCORPIO and csm_share. The second stage builds all configured components through the official full-model CMake project and links `ki-build/e3sm.exe`. ELM's isolated `src/CMakeLists.txt` is a unit-test route and is not the installation target.

The audited host adaptations are GNU Make's actual `/usr/bin/make` path; ARM64 `-mcmodel=small`; SCORPIO's supported `SPIO_CMAKE_OPTS=-DCMAKE_POLICY_VERSION_MINIMUM=3.5` for CMake 4; netCDF's documented `NETCDF_ENABLE_LEGACY_MACROS`; and MPI compiler include precedence favoring newly built SCORPIO headers/modules over unrelated PIO already installed in the runtime. All are build configuration changes. No model physics is patched. Full source checkouts already include EAM sources referenced by global compiler flags; sparse checkouts also need `components/eam/src/dynamics/fv` and `components/eam/src/dynamics/se`.

Native compile and link were demonstrated locally: Mach-O ARM64 `e3sm.exe`, 22,839,416 bytes, SHA-256 `7043f360441a14822fa0322c31677458168b2c732b1b26facde77d58ad24e099`. The fresh build completed in approximately 340 seconds after support libraries were built. These are local audit facts, not a DS installation pass.

This upstream executable has no help CLI. A bounded `--help` invocation in an empty temporary directory loads native libraries, initializes MPI and returns 233 with `(cime_cpl_init) :: namelist read returns an end of file or end of record condition` and `MPI_Abort(MPI_COMM_WORLD, 1001)`. Source `driver-mct/main/cime_comp_mod.F90` lines 3712–3719 reads the absent `drv_in` before model initialization and causes this exact abort. The probe creates only an empty `fort.99` file. This narrowly identified startup boundary establishes native loading; arbitrary MPI aborts or other nonzero exits are failures. Use `FI_PROVIDER=tcp` and `FI_TCP_IFACE=en0` for the audited local MPI probe. Do not supply case namelists or execute a simulation as an installation check.
