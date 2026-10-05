# ROMS — foundation test case: "upwelling"

The official ROMS **UPWELLING** test case: wind-driven upwelling and downwelling over a
periodic channel. Grid 41 x 80 x 16, grid, initial state and forcing all made inside ROMS
by analytic code (no NetCDF input files). 1440 steps of 300 s = 5 days.

| | |
|---|---|
| Source | github.com/myroms/roms, commit `bf66be4` (2026-03-12), ROMS version 4.3 |
| Files | `ROMS/External/roms_upwelling.in`, `ROMS/External/varinfo.yaml`, `ROMS/Include/upwelling.h` |
| Licence | MIT (`License_ROMS.md`, Copyright (c) 2002-2026 ROMS) |
| Engine | serial `romsS` built with `ROMS_APP=UPWELLING` (gfortran, -O3 -ffast-math) |
| KI | `ROMS` |

`inputs/` holds the three official files, unmodified, taken with `git show HEAD:<path>`:

- `roms_upwelling.in` — the run settings (ROMS reads it on stdin).
- `ROMS/External/varinfo.yaml` — variable metadata; kept at this path because
  `roms_upwelling.in` points to `ROMS/External/varinfo.yaml` relative to the run folder.
- `upwelling.h` — the case's CPP header. It is **not read at run time**: ROMS compiles it
  into the binary. It is kept here so the case is complete and you can rebuild the binary.

## Run
```
python run_reference.py    # finds romsS ($ROMS_BIN, --roms-bin); 0=PASS 2=FAIL 3=missing
```
Server default binary:
`/home/server/knowledge-dissection-toolkit/auto_dissect/_work/ROMS/source/repo/build_upwelling/romsS`.
The binary must be an UPWELLING build; the script checks that the log says
`Header file : upwelling.h`. To build one from the ROMS source:
`cmake <roms> -DROMS_APP=UPWELLING -DMY_HEADER_DIR=<roms>/ROMS/Include && make`.

The script copies the inputs to a fresh temp folder, runs ROMS through the KI tool
`tools/run_roms.py` (its `run_roms()` function, serial, 1 rank), uses the tool's own log
scan and output-file check, then checks `expected.json`. Run time about 36 s, about 140 MB
RAM; it writes about 320 MB of NetCDF output to the temp folder, then deletes it.

## Expected
No official reference output for this case is on the server (the myroms `roms_test`
repo is not here, and the ROMS source tree ships no stored output or benchmark log), so
the expected values were **recorded from our own runs** on 2026-10-05. Four runs (one
direct, one through the tool's command line, two through `run_reference.py`) gave
identical results; the NetCDF files of two runs were compared variable by variable and
are bit-identical.

Checks: return code 0 and `ROMS: DONE` in the log; 1441 energy rows (steps 0..1440);
21 history records ending at 432000 s; at step 1440 kinetic energy 0.02448788, potential
energy 658.5713, total energy 658.5958 (start 658.5677), volume 3.884376e11 m3 with zero
change (volume is kept in the closed channel), max speed 0.6426 m/s; last history record
temperature 14.51 to 22.07 C (mean 18.55), max sea level 0.0964 m, strongest current
u = -0.6424 m/s. Tolerances sit near the print precision of the ROMS log; they are not
official ROMS tolerances.

## Notes on the engine
The ROMS source checkout on the server has 3 local edits not in git: NetCDF link flags in
`Compilers/roms_functions.cmake`, an extra `LEKIMA`-only block in `ana_vmix.h`, and a
safety check in `inp_par.F` that only stops the run if an array was never set up. None of
these touches the UPWELLING path, so the binary runs the official case as published.

## Known KI gaps
- The KI preflight checks `.../repo/build/romsS`, which is a **CALCURRENT** build, not
  UPWELLING. A ROMS binary is tied to one case (the header is compiled in). Fed this
  case's `roms_upwelling.in`, that binary stops with `Found Error: 5` in `read_phypar.F`.
  This case uses the separate UPWELLING build in `build_upwelling/`.
- `tools/run_roms.py` on the command line prints only the last 500 characters of the ROMS
  log, so the energy / volume table (the usual ROMS health check) is lost. That is why
  this script imports the tool and calls `run_roms()` directly, which returns the full log.
- `tools/run_roms.py` warns about "missing input files" (grid, initial, forcing, boundary,
  climate, tide, stations, floats) even though this analytic case reads none of them;
  the tool does not look at the CPP options to know which files are used.
- The tool's build path passes `-DAPP=...` to CMake, but ROMS's CMake reads `ROMS_APP`.
  Not used here (no build is done), noted only.
