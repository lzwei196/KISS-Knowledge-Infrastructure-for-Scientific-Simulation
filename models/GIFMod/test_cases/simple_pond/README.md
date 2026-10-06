# GIFMod — foundation test case: "simple_pond"

This case uses the **unmodified official GIFMod wizard template `Simple_pond`** from the
upstream repository https://github.com/USEPA/GIFMod, commit
`2a314750418099ca51a100d824381924ba982c91` (file `bindata/templates/Simple_pond.wiz`).
The template builds one pond with 4 constituents (DO, NH3, NOx, DOC) and 3 reactions
(nitrification, aerobic growth, anoxic growth). We supply the 4 wizard answers that have no
default in the template — start 2020-01-01, end 2020-01-31, initial depth 1 m, bottom area
100 m² (`inputs/wizard_answers.json`); the other 8 reaction parameters use the template
defaults. Reference values were recorded from our own repeated runs, not supplied by upstream.

**The engine is a patched fork, not upstream GIFMod.** Upstream GIFMod is a Qt GUI with no
command-line run mode, so the server engine is built from a patched copy of the same commit.
The full patch is in `gifmod_patches.diff` (16 files, +90 lines):

1. `src/GUI/qcustomplot.h`: add `#include <QPainterPath>` (needed with Qt ≥ 5.14; build fix).
2. `src/GUI/utility_funcs.cpp`: add `#include <cmath>` (`fmod`; build fix).
3. `src/GUI/main.cpp`: a headless driver: `--wizard T.wiz [--param name=value ...] --save out.GIFMod`,
   `--script S --save out.GIFMod`, `--model M.GIFMod`. It fills template defaults, builds and saves
   the model, presses the GUI's own "Run Model" action and exits 0 only if results exist.
4. A final `return` added to 20 non-void functions in 12 files that fall off the end upstream. With
   GCC 13 -O2 this undefined behaviour made the wizard loop forever until memory ran out.
5. The driver closes modal dialogs every 300 ms (the solver ends with a "Simulation Finished!" box).
6. `src/GUI/Wizard/wiz_assigned_value.cpp`: optional debug print when `GIFMOD_DEBUG_WIZ` is set.

| | |
|---|---|
| Engine | GIFMod patched fork of USEPA/GIFMod 2a31475; Qt 5.15.15, GCC 13.3; binary sha256 `1d83043c…99f25`; run headless via `gifmod_headless.sh` (`QT_QPA_PLATFORM=offscreen`) |
| Source | template `bindata/templates/Simple_pond.wiz` (+ its icon `simple_pond_w_rxns.png`, not used by the run) |
| Licence | see the upstream USEPA/GIFMod `LICENSE` |
| KI | `GIFMod`, real-engine tool `tools/run_gifmod_engine.py` |

## Run
```
python run_reference.py              # uses <KI>/tools/run_gifmod_engine.py; 0=PASS 2=FAIL 3=missing
python run_reference.py --run-tool /mnt/disk1/Hydrocraft_server/models/GIFMod/knowledge_infrastructure/tools/run_gifmod_engine.py
```
It copies the template to a fresh temp dir and runs it through the KI tool with the 4 answers.
The engine is found by `--binary`/`--wrapper` → `$GIFMOD_BINARY`/`$GIFMOD_HEADLESS` →
`/home/server/engine_builds_20261006/gifmod/install/gifmod_headless.sh`; a binary without the
headless driver is refused. Missing engine → `MISSING DEPENDENCY`, exit 3.

## Expected (recorded 2026-10-06; repeat runs identical, see below)
- engine finishes normally (exit 0, `hasResults=1`, "experiment1 finished", "Simulation ended.")
- GIFMod's model check: 0 errors, 3 warnings (pond length, width and Manning's n unset)
- `hydro_output`: 3002 records, serial day 43831 (2020-01-01) to 43861.01 (one record past the end
  date — the engine writes it); storage 100 m³ and head 1 m at every record; evaporation 0
- all 8 water-quality series (DO, DOC, NH3, NOx; aqueous and sorbed) stay 0
- `output_MB`: 101 records, mass-balance error 0 at every record

The pond has no inflow and no starting concentration, so the physics is trivial: this case
proves the engine builds the model, solves it and writes its outputs, not a water-quality result.
Repeat check: two wizard runs, a re-run of the saved `.GIFMod`, and the same model built from a
GIFMod script all gave byte-identical `wq_output` and `output_MB`, and identical `hydro_output`
except the `LAI_Pond` column.

## Known issues (plain words)
- `LAI_Pond` in `hydro_output` is uninitialised memory in the engine (values like 6.95e-310 that
  change from run to run). It is not checked and must not be used.
- Every run rewrites `install/gmon.out` (upstream `GIFMod.pro` builds with gprof `-pg`) and adds
  lines to `install/recentFiles.txt` in the engine folder.
- The engine is a local fork; we have not proven it gives the same science as upstream GIFMod
  beyond this case. The added `return` statements only touch paths that had no defined result.

## Known KI gaps
- `tools/run_gifmod.py --mode run` cannot run a model: upstream GIFMod ignores the project
  argument and only opens the GUI. Use `tools/run_gifmod_engine.py`.
- `tools/parse_gifmod_output.py` cannot read real GIFMod output (`names,` header + (t, value)
  pairs); it fails with exit 1. `run_gifmod_engine.py` writes the parsed CSV itself.
