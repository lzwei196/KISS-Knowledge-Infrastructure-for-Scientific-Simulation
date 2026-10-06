# COAWST foundation test case: `inlet_test_coupled` (official test application Inlet_test, Coupled)

## What it is
The official COAWST test application **Inlet_test**, variant **Coupled** (`Projects/Inlet_test/Coupled`).
It is the default application in the official `build_coawst.sh` (`COAWST_APPLICATION=INLET_TEST`).
A tidal inlet between two basins, 15 km x 14 km, flat bottom with a channel:

- **ROMS** (ocean): 75 x 70 cells, 8 layers, time step 60 s, 720 steps = 12 hours. Tide-like forcing,
  start state and fluxes come from analytical code in the header (`ANA_*` options), with suspended
  sand, bed load and bed change (morphology).
- **SWAN** (waves): the same 76 x 71 grid, 36 directions, 60 s steps for 12 hours. Waves of 1 m,
  10 s come in from the north side.
- The two models swap data through **MCT** every 600 s (ROMS sends water level and currents to SWAN;
  SWAN sends wave height, period, direction and dissipation to ROMS).

It runs on 2 MPI ranks (1 ocean, 1 wave, as set in `coupling_inlet_test.in`) and takes about 9 minutes.

## Source and licence
- Repository: https://github.com/DOI-USGS/COAWST (COAWST 3.8), branch `main`, commit
  `79bd6033689b80b1d52f9868d52dfaf6c6e3979b` (2026-03-11). ROMS/TOMS 4.1, SWAN 41.45, MCT 2.6.0.
- Licence: COAWST is in the public domain (USGS) and CC0 1.0 (`LICENSE.md`); its parts keep their
  own licences: ROMS (MIT/X-style, `ROMS/License_ROMS.txt`), SWAN (GPL-3.0), MCT (Argonne copyright,
  `Lib/MCT/COPYRIGHT`).
- `inputs/` holds the 12 files of `Projects/Inlet_test/Coupled` that are tracked in git, plus
  `ROMS/External/varinfo.dat` (named by `VARNAME`), each taken with `git show 79bd6033:<path>`,
  unmodified, in the same folder layout (the official files use paths relative to the COAWST root).
  `inlet_test.h` and the two `ana_*.h` files are build-time files (they were compiled into the
  program); they are kept here so the case is complete.
- COAWST ships **no reference output** for this case.

## Engine
`coawstM` built for INLET_TEST on this server on 2026-10-06:
`/home/server/engine_builds_20261006/coawst/COAWST/coawstM`
(sha256 `c9cfaf10ea99796573d75b1d378cadf73ca15b739ebcc5274922f290e3614e97`).
Built from a `git archive` copy of the commit above with the official `build_coawst.sh`, changed only
in a copy outside the source (`MY_ROOT_DIR`, and `MCT_INCDIR`/`MCT_LIBDIR` for MCT built in the same new
tree with `FCFLAGS=-fallow-argument-mismatch`). gfortran 13.3.0, Open MPI 4.1.6 (`mpif90`),
netCDF-Fortran 4.5.4. One build-environment setting: `FC=mpif90`, because SWAN's CMake step otherwise
picks `/usr/bin/f95` and fails on `mpif.h`. No source or input file was changed.
Build log: `/home/server/engine_builds_20261006/coawst/BUILD_LOG.md`.

COAWST builds one program per application. The other server program,
`/home/server/knowledge-dissection-toolkit/auto_dissect/_work/COAWST/source/repo/coawstM`, is built for
SANDY (the KI default) and cannot run this case.

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py [--coawst-bin PATH] [--keep]
```
Program lookup: `--coawst-bin` -> `$COAWST_INLET_TEST_BIN` -> server default (above). A `coawstM` on
PATH is not used, because it may be built for another application. A chosen program that is not an
executable file gives exit 3. Needs `mpirun` and python `netCDF4` (else exit 3).

The script copies `inputs/` to a fresh temp dir, puts a byte-identical copy of
`coupling_inlet_test.in` at the run root (see Known KI gaps), runs the KI tool:
```
python tools/run_coawst.py --binary <coawstM> --config coupling_inlet_test.in --nprocs 2 --timeout 0
```
(which runs `mpirun -np 2 coawstM coupling_inlet_test.in`), checks `expected.json`, and deletes the temp
dir. Exit 0 = PASS, 2 = checks failed, 3 = engine or dependency missing.

## Expected results
All values are **our own run values** (regression values), not official reference results.
Two runs (one direct `mpirun`, one through the KI tool, each in a fresh folder) were identical in all
892 NetCDF variables of the 7 output files and in all SWAN `.mat`, `.table`, `.spc2d` and restart files
(only SWAN's `PRINT01` log differs, by its start time). Float checks use 1e-6 relative tolerance; this
is only proven for this build (the same values on another compiler or machine are not tested).
Counts use exact match.

Checks: 13 history records, last time 43200 s, last ROMS step 720, 73 ROMS-from-SWAN data exchanges
(start + every 600 s), 721 station records, no NaN/Inf in final water level and wave height; at 12 h:
max water level 0.2484 m, max |depth-mean u| 1.559 m/s, max wave height 1.157 m (ROMS `Hwave` and SWAN
`hsig.nc`), mean wave height 0.5101 m, SWAN Hsig at point1 0.892 m, max bed change 1.057 m, max suspended
sand 15.69 kg/m3, ROMS kinetic energy 0.0274. Finished check: model return code 0 (from the tool's JSON)
and the model line `ROMS/TOMS: DONE`.

Notes on the official inputs (no change made):
- `coupling_inlet_test.in` names `scrip_weights_inlet_test.nc`, which is not in git. It is not read:
  ocean and waves share one grid and `inlet_test.h` sets no `MCT_INTERP_*` option.
- `ocean_inlet_test.in` names `ocean_ini.nc`, `ocean_bndry.nc`, `ocean_clm.nc`, `ocean_frc.nc`, which do
  not exist. They are not read (analytical options). The runs prove both points.

PASS output tail: see the end of this file.

## Known KI gaps (not fixed here)
- `tools/run_coawst.py` runs the model in the folder of the `--config` file. The official files use
  paths relative to the COAWST root (`Projects/Inlet_test/Coupled/...`), so passing the official
  `Projects/Inlet_test/Coupled/coupling_inlet_test.in` fails. Workaround here: a byte-identical copy at
  the run root.
- COAWST cuts long file names: a long absolute `--config` path (e.g. under `/tmp/claude-1000/...`) is
  cut and the run stops at once (`READ_COAWST_PAR - Unable to open coupling script`). This case passes a
  short relative name.
- `tools/run_coawst.py` exits 0 even when the model fails (its JSON then says `"status": "failed"`), so
  this case checks the JSON `returncode` and `status`.
- Its NaN/Inf watch matches any line with "INF" or "NAN" in it (e.g. `Information`, `ninfo`), so a normal
  run gets `completed_with_warnings` with false warnings.
- Its timeout check runs only when the model prints a line; a silent hang is not stopped by it. This case
  has its own watchdog: after 1110 s it stops the tool, mpirun and the model ranks, each by its own PID,
  and checks they are gone (tested: all three stopped, none left). The tool's own timeout is switched off (`--timeout 0`), because
  it kills only mpirun and could leave model ranks behind.
- The KI default program (preflight, SKILL.md) is the SANDY build; the Inlet_test build is passed with
  `--binary`. The live KI was not changed.

## PASS output tail (2026-10-06, through the KI tool, 528 s)
```
  OK bath_change_absmax_m: 1.05676651
  OK sand_01_max_end_kgm3: 15.69237518
  OK roms_kinetic_energy_end: 0.02740462
PASS: COAWST Inlet_test (ROMS+SWAN coupled) matches expected.json.
```
