# WASP — foundation test case: "steady_state"

Authentic foundation case: EPA's own **WASP "Steady State" example**
("WASP Model Steady State Example (zip)" on https://www.epa.gov/hydrowq/wasp-model-examples).
It is a 10-segment river with kinematic-wave flow, an upstream boundary and an NPDES point
source, and 5 systems (Upstream BOD, NPDES BOD, DO, Solids, Temp), run for 4.96 days.
`inputs/` holds the 4 files of EPA's zip, unmodified.

| | |
|---|---|
| Engine | US EPA WASP 8.5.0 (`waspccli.exe`, banner "Wasp suite version 8.5.0, Gui develop af12325 dirty, Model master e86fb43"), Windows build run under WINE 9.0 |
| Installer | `wasp-version-8.5.0-install-64-bit-10-25-2025.exe` from epa.gov, sha256 `2bb410b59ead76d5ba3681f05f61c4b1193a1be8b5393ab7a33f234957b293d4` |
| Example | `steady-state-example.zip` (https://www.epa.gov/sites/default/files/2018-05/steady-state-example.zip), sha256 `6b9571929c7c1abdbacc43c37447b40f17240e5c2e3d45c872c672539c5f1579` — a separate EPA download, not inside the installer |
| Licence | US EPA public software release (US Government work); WASP is distributed as Windows binaries only |
| KI | `WASP`, real-engine tool `tools/run_wasp_engine.py` |

## Files in `inputs/`
- `SteadyState.wif` — the WASP input file. This is the only file the run uses.
- `SteadyState.xlsx` — EPA's workbook used to build the model (segments, weather, boundaries, constants). Input data, not results.
- `4-Steady State Example.pdf`, `4-Steady State Example.pptx` — EPA's tutorial for this example.

## Run
```
python run_reference.py                    # uses <KI>/tools/run_wasp_engine.py; 0=PASS 2=FAIL 3=missing
python run_reference.py --run-tool KISSPATH_KI_ROOT/WASP/knowledge_infrastructure/tools/run_wasp_engine.py
# a copy of the KI on another machine: point it at that machine's WASP install
WASP_ENGINE_ROOT=/path/to/wasp python run_reference.py      # uses /path/to/wasp/wineprefix
WASP_WINEPREFIX=/path/to/wineprefix WASP_WINE=/usr/bin/wine python run_reference.py
```
It copies `SteadyState.wif` to a fresh temp dir and runs it through the KI's real-engine tool
(`wine C:\WASP8\wasp\bin\waspccli.exe SteadyState.wif`). The tool checks the engine's own line
"run successfully closed out", the `.OUT` file and a valid `.BMD2`, then extracts all 9
variables for all 10 segments with EPA's `BMD2_Extract.exe`. The engine is found by
`--wineprefix` → `$WASP_WINEPREFIX` → `$WASP_ENGINE_ROOT/wineprefix` →
`KISSPATH_HOME/engine_builds_20261006/wasp/wineprefix` (this server),
and wine by `--wine` → `$WASP_WINE` → PATH. If the engine or WINE is missing the script prints
`MISSING DEPENDENCY` and exits 3; it never runs the KI's analytic surrogate instead.

## Expected (recorded 2026-10-06 from our own runs; two clean runs were byte-identical)
EPA ships no reference output for this example, so the values come from our runs.
- engine closes out normally; 10 segments, 9 variables, 355 output times (2012-07-01 00:00 to 07-05 22:58)
- 31 "Failed to locate time function" messages (kept as a check: a change means the file is read differently)
- end of run, segment 1 (river outlet): DO 7.2348 mg/L, CBOD 105.904 mg/L, outflow 0.35672 m3/s, volume 2653.13 m3; largest DO there 11.5205 mg/L
- end of run, segment 9 (point source): DO 5.7412 mg/L, CBOD 117.008 mg/L, water temperature 21.372 °C

## Known issues (plain words)
- The example was saved in 2017 and is read by WASP 8.5. The engine prints 31 lines
  "ERROR: Failed to locate time function" and wine returns exit code 2, but the run closes out
  normally and writes all outputs. We have **not** checked whether these missing time functions
  change the science of this example. Treat the numbers as a repeat-run baseline for this engine
  build, not as a validated physical result. (For example, water temperature starts at 0 and is
  still rising at the end of the 5-day run.)
- `waspccli.exe` exit codes are not reliable (2 on this good run; a broken `.wif` can make it spin
  forever with no output). The KI tool judges success from the close-out line and the output files,
  and stops a run after a time limit.
- `BMD2_Extract.exe` has no published manual; the control-file layout the KI tool writes was worked
  out by testing it (see the tool's source).

## Known KI gaps
- The KI's older tools (`run_wasp.py`, `convert_*_to_wasp.py`, `parse_output_wasp.py`) are an analytic
  Python **surrogate**, not EPA WASP. They cannot build or read `.wif`/`.BMD2` files and are not used here.
