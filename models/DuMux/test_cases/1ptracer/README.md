# DuMux foundation test case: `1ptracer` (official example)

## What it is
The official DuMux example `examples/1ptracer`. It runs in two stages on a 2D unit
square with 50 x 50 cells:

1. Steady single-phase flow. Pressure is fixed at the bottom and top, so water flows
   upward. Permeability is a random field made with a fixed seed, with a lower-permeability
   lens in the middle.
2. Tracer transport. A tracer starts in the bottom 10% of the domain and is carried by the
   flow from stage 1. Time step 10 s, end time 5000 s (500 steps), output every 500 s.

DuMux builds one program per problem, so the "engine" for this case is the compiled
example program `example_1ptracer`.

## Source and licence
- Repository: https://git.iws.uni-stuttgart.de/dumux-repositories/dumux.git
- Version: DuMux 3.10, branch `releases/3.10`, commit `3e151aebf005bf500c0d0e05563c0e8c41583eef`
  (`3.10.0-11-g3e151aebf`), with DUNE 2.10.
- Licence: GPL-3.0-or-later (DuMux).
- All files were taken with `git show HEAD:<path>` from that commit, so they are unmodified:
  - `inputs/params.input`: the example's parameter file (the only runtime input).
  - `inputs/source/`: the example's C++ source and CMakeLists.txt (for reference; the
    program is already built on the server).
  - `reference/test_1ptracer_pressure-reference.vtu`,
    `reference/test_1ptracer_transport-reference.vtu`: the official DuMux test-suite
    reference results (from `test/references/`).
  - `compare/dumux_fuzzycompare_legacy.py`: the official DuMux compare script
    (from `bin/testing/`).

## Engine
`example_1ptracer`, built on this server at
`/home/server/knowledge-dissection-toolkit/auto_dissect/_work/DuMux/dumux/dumux/build-cmake/examples/1ptracer/example_1ptracer`.

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py [--dumux-bin PATH] [--keep]
```
Binary lookup: `--dumux-bin` -> `$DUMUX_BIN` -> `which example_1ptracer` -> server default path.
The script copies `inputs/params.input` to a fresh temp dir, runs the program there through
the KI tool `tools/run_dumux.py` (its `run_simulation` function), checks `expected.json`,
and deletes the temp dir. Exit 0 = PASS, 2 = checks failed, 3 = engine or KI tool missing.
It runs in under a second.

Command used (the official ctest command plus one extra key, see below):
```
example_1ptracer params.input -Problem.Name example_1ptracer -Problem.FlowDirection 1
```
It sets `DUMUX_NUM_THREADS=4` and `OMP_NUM_THREADS=4`. Without a limit the OpenMP build
starts one thread per core (192 here) and runs about 100 times slower. A run with all
threads and a run with 4 threads gave byte-identical output files.

## Expected results
The main check is the same one the official DuMux ctest `example_1ptracer` does: the
official fuzzy compare (relative tolerance 1e-2, absolute 1.5e-7 x max value) of every
field in every cell:
- `1p.vtu` vs `test_1ptracer_pressure-reference.vtu` -> equal
- `example_1ptracer-00010.vtu` (t = 5000 s) vs `test_1ptracer_transport-reference.vtu` -> equal

Summary values taken FROM THE OFFICIAL reference files (tolerance = the official relative
1e-2): min/max/mean pressure (100098 / 109902 / 105004.36 Pa), mean permeability
(9.647e-10 m^2), max and mean tracer mole fraction at 5000 s (9.97466e-10 / 9.99975e-11),
max velocity (7.137e-5 m/s), mean vertical velocity (6.996e-6 m/s).
Our run matches them to all printed digits (largest difference 1.5e-8 relative, in the
tracer mean).

Run counts from the model (own run): 500 time steps, final time 5000 s, 11 tracer output
files, last time in the .pvd = 5000 s, starting tracer mean = 1e-10. Finished check:
return code 0 and the model's own line `Simulation took ... seconds`.

Recorded 2026-10-05. Two full runs of `run_reference.py` both passed with the same numbers.

PASS output tail:
```
  OK fuzzy_fail_pressure: 0
  OK fuzzy_fail_transport: 0
  OK n_time_steps: 500
  OK final_time_s: 5000
  OK n_tracer_vtu: 11
  OK pvd_last_time_s: 5000
  OK tracer_x_mean_start: 1e-10
PASS: DuMux 1ptracer example matches the official DuMux reference results.
```

## The extra key `-Problem.FlowDirection 1`
The server program was built from a `problem_1p.hh` that was edited during the KI build
(the source tree shows it as changed against git). The edit adds `Problem.FlowDirection`,
whose default (0) makes the flow go left to right instead of bottom to top. With that
default, the official `params.input` run does not match the example and crashes at step 136
(`BiCGSTABSolver: defect=inf`). Any value other than 0 or 2 runs the original, unedited
bottom-to-top code. The input files are not changed; only this command-line key is added,
and the full-field compare against the official references proves the result is the
official one. A clean, unedited DuMux build does not use this key; DuMux only lists unused keys at the end of a run and goes on (not tried here, as no clean build exists on the server).

## KI gaps (status 2026-10-06)
- **Still open:** The server binary was built from a KI-edited `problem_1p.hh` whose default flow
  direction differs from the official example (see above). The official example only
  reproduces with `-Problem.FlowDirection 1`.
- **Fixed in `ae00b7c`:** `tools/run_dumux.py` now runs the program in a work dir (default: the
  current directory), never in the build tree, and no longer searches the source tree for a
  missing params file (it fails with `params_not_found`). Before: it always ran in the
  binary's own folder and searched the whole source tree, so this case calls only its
  `run_simulation` function, with a temp working dir. The workaround in `run_reference.py` is
  kept so the case also runs with older tool versions.
- **Fixed in `ae00b7c`:** `tools/run_dumux.py` sets a thread limit (`--threads`,
  `DUMUX_NUM_THREADS` or `OMP_NUM_THREADS`, else a small default). Before: it did not limit
  OpenMP threads, so each run spun all 192 cores (about 30 s and ~90 CPU-minutes instead of
  under 1 s).
- **Fixed in `ae00b7c`:** `tools/parse_dumux_output.py` maps `pressure` to DuMux's `p` and takes
  times from the `.pvd`. Before: it defaulted to `pressure`, which this example does not write,
  so with defaults it returned NaN columns. This case reads the .vtu files directly; the
  workaround in `run_reference.py` is kept so the case also runs with older tool versions.
- **Still open (upstream, not a KI issue):** The official command-line wrapper
  `bin/testing/fuzzycomparevtu.py` passes its arguments to `compareVTK` in the wrong order and
  crashes (`'bool' object is not iterable`); this case calls `compareVTK` the way the official
  `dumux_runtest.py` does.
