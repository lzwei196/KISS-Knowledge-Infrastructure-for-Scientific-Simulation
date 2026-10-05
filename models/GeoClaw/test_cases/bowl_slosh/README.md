# GeoClaw — foundation test case: "bowl_slosh"

Official foundation case: the Clawpack regression test `geoclaw/tests/bowl_slosh`
(github.com/clawpack/geoclaw, commit 37d0bf5). Water sloshes in a parabolic bowl
(depth 0.1 m, domain 4 m x 4 m), 41x41 base grid plus one finer AMR level (ratio 4),
run to t = 0.5 s, with one gauge at (0.5, 0.5) and one fgmax grid. It is the test form of
the `examples/tsunami/bowl-slosh` example the KI SKILL.md was checked on, and unlike the
example it ships official reference data.

`inputs/` holds all files of the test folder, unmodified (taken with `git show HEAD:`):
`setrun.py`, `Makefile`, `qinit.f90`, `maketopo.py`, the official `regression_tests.py`,
plotting helpers, and `regression_data/` (official gauge and fgmax reference values).

| | |
|---|---|
| Engine | GeoClaw from Clawpack 5.14.0: Python package + Fortran sources (geoclaw 37d0bf5, amrclaw 98ba14a = v5.14.0, clawutil 02bcfb4, riemann f4ac312), gfortran 13.3.0 |
| Source | github.com/clawpack/geoclaw `tests/bowl_slosh` |
| Licence | BSD 3-Clause (Clawpack Developers) |
| KI | `GeoClaw` |

## How GeoClaw runs
GeoClaw has no single prebuilt program. Each case is compiled with `make .exe` (its own
`qinit.f90` plus the Clawpack Fortran library) into `xgeoclaw`, which then runs. Make puts
object files next to the library sources, so `run_reference.py` first copies the Clawpack
`src/` folders into a temp dir and compiles there. The real source tree is never written to.

## Run
```
python run_reference.py    # 0=PASS 2=FAIL 3=missing dependency
#   --claw-dir    (or $CLAW)        Clawpack source tree with amrclaw/ clawutil/ geoclaw/ riemann/
#   --claw-python (or $CLAW_PYTHON) Python with clawpack installed
#   --fc          (or $FC)          Fortran compiler, default gfortran
```
Server defaults: `/home/server/knowledge-dissection-toolkit/auto_dissect/_work/GeoClaw/clawpack`
and `.../_work/GeoClaw/venv/bin/python`. `run_reference.py` itself only needs the standard
library; it runs everything else with the Clawpack Python. It uses OMP_NUM_THREADS=4.

Steps (all in a fresh temp dir, deleted at the end): copy sources and inputs, make the bowl
topography with the official `maketopo.py` (what `make topo` runs), run the KI's own
`tools/run_geoclaw.py --use-makefile` (setrun.py, then `make .exe`, then `xgeoclaw`), read
frames with the KI's `tools/parse_geoclaw_output.py`, and read gauge 1 and the fgmax grid with
Clawpack's own readers, exactly as the official `regression_tests.py` does. Takes about 4 s.

## Expected
Values come from the **official `regression_data/` files**, with the official tolerances
(clawpack `check_gauges`: rtol 1e-14, atol 1e-8 on hv and eta; `check_fgmax`: rtol 1e-14):
55 gauge records to t = 0.4931615 s, eta max 0.04513636 / min 0.025, hv max 0.05863194,
final hv 0.05160544, every hv and eta value matching the official gauge file, fgmax sums
h = 19.690880033641498 and s = 257.79961463. Plus: 2 output frames, last at t = 0.5 s, and
a normal finish (all steps rc 0 and the line "end of AMRCLAW integration" in `fort.amr`).

On 2026-10-05 three clean runs matched the official data exactly (gauge h, hu, hv, eta
max difference 0 over all 55 records; fgmax sums equal). Runs repeat exactly.

## KI gaps (status 2026-10-06)
- **Fixed in `d78c500`:** `run_geoclaw.py` now writes output to `_output/` like Clawpack's `runclaw` and exits non-zero only on a real failure; the same commit changed `run_reference.py` to read `_output/`. Before: all output landed in the run folder and the tool wrongly warned "CRITICAL: No fort.q files produced".
- **Fixed in `d78c500`:** `parse_geoclaw_output.py` now reads Clawpack 5.x `fort.q` grids and `gaugeNNNNN.txt` files. Before: it found 0 grids (h_max and speed_max were 0) and looked for an old `fort.gauge` file, so only frame count and frame time were taken from it.

  The workaround in `run_reference.py` (gauge and fgmax values read with Clawpack's own readers) is kept so the case also runs with older tool versions.
- **Fixed in `891d03f`:** the preflight now checks clawpack in the GeoClaw venv (`CLAW_PYTHON` / `CLAW`), proves the per-example build works with a tiny case in a temp dir, and shows the chile2010-only `xgeoclaw` as info. Before: it checked `import clawpack` with `/usr/bin/python3.12` (3 import FAILs) and pointed at the chile2010-only binary.
- **Still open (upstream, not a KI issue):** `setrun.py` still sets `deep_depth` and `max_level_deep`; Clawpack prints a warning that these are ignored since v5.8.0. This is in the official file and does not change results.
