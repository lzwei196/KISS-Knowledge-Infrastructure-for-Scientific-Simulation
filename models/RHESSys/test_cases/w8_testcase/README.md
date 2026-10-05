# RHESSys foundation test case: W8 official test case

## What it is
RHESSys's own test case from its git repository (`Testing/` folder, `TestCase.Rmd`).
It is a small forest catchment, Watershed 8 (W8) in the HJ Andrews Experimental
Forest, Oregon, USA. The model runs from 1988-10-01 to 2000-10-01 with plant growth
on (`-g`) and writes daily basin output from 1989-10-01 (4018 days). The RHESSys
team uses this case to check that code changes do not break the model.

## Source
- Repository: https://github.com/RHESSys/RHESSys, commit `f9d1bbf8d161aa55b6a51061dc320188ead44962`
  (2024-03-05). Server copy: `/home/server/knowledge-dissection-toolkit/auto_dissect/_work/RHESSys/source/repo`.
- `inputs/` = the unmodified files from `Testing/` at that commit, taken with `git show HEAD:<path>`
  (the server folder has leftover run outputs, so files were taken from git, not the folder):
  worldfile + header, flow table, 6 parameter (def) files, climate base station + daily rain/tmax/tmin,
  tec file. Total about 2 MB.
- `reference/` = official files used for comparison only, also unmodified from git:
  `base_basin_daily.csv` (official base output), `testing_filter.yml` (the output filter that
  made it), `TestCase.Rmd` (the official test procedure), `rhessystest.py` (RHESSys's own water
  balance test, from `rhessys/test/`).
- Licence: the RHESSys repository has no licence file.

## Engine
`rhessys7.4` built in the server source tree (the binary the KI preflight finds). The makefile says
version 7.4; `rhessys7.4 -version` prints `RHESSys Version: 5.14.3`.
Note: the server source tree has one uncommitted edit, and the binary was built after it
(`rhessys/cycle/canopy_stratum_daily_F.c` line 1160 changed `rnet_evap_night = 0.0` to
`rnet_evap_day = 0.0` when the daytime net radiation is negative). This looks like a local bug fix.
It may change results slightly against an engine built from clean upstream code.

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py [--rhessys-bin PATH] [--keep]
```
Binary lookup: `--rhessys-bin` -> `$RHESSYS_BIN` -> `which rhessys7.4` -> server default path.
The script copies `inputs/` to a fresh temp dir, runs the official `TestCase.Rmd` command line
through the KI tool `tools/run_rhessys.py`, checks `expected.json`, and deletes the temp dir.
Exit 0 = PASS, 2 = checks failed, 3 = engine missing. A run takes about 10 seconds.

Official command (from `TestCase.Rmd`):
```
rhessys7.4 -t tecfiles/tec.test -w worldfiles/w8TC.world -whdr worldfiles/w8TC.hdr -r flowtables/w8TC.flow
  -pre out/test -s 0.355794 651.390265 -sv 0.355794 651.390265 -svalt 1.083102 1.193924
  -gw 0.116316 0.916922 -st 1988 10 1 1 -ed 2000 10 1 1 -b -g
```
(The Rmd writes `-svalt 1.083102 1.193924,` with a stray comma; the engine reads both forms the same.
The KI tool run and a direct run of the Rmd line gave byte-identical output files.)

## Expected results
Values come from our own clean runs (two runs, byte-identical output). Checks (tolerance 1e-5 relative):
- finished normally: return code 0 and RHESSys's end line `time cost = ... seconds`
- 4018 daily rows in basin and growth output, first day 1989-10-01, last day 2000-09-30
- precipitation total 13165.75 mm, streamflow total 6604.37 mm, peak daily streamflow 86.57 mm,
  evaporation + transpiration total 6588.35 mm
- mean saturation deficit 1348.86 mm, peak snowpack 219.09 mm, mean LAI 9.673
- last-day plant carbon 70.58, soil carbon 36.24, litter carbon 1.094 kgC/m2
- RHESSys's own water balance test (`rhessystest.py`, max 3-day mean |error| < 1e-5):
  2.33e-6, passes.

### Why the official base output is not the pass gate
The official base output `reference/base_basin_daily.csv` was made with the output filter
`testing_filter.yml`. This engine crashes (segfault inside the filter parser,
`add_to_output_filter_variable_list`) when given that filter with `-of`, so the same CSV cannot be
made. Comparing our legacy output with it (same units), the means differ: streamflow +0.40%,
saturation deficit -0.82%, root-zone storage -5.87%, LAI -4.32%, snowpack +0.20%; litter carbon
about -22%. `TestCase.Rmd` gives no pass limit for these. The likely cause is that the base was made
with a different code version and/or the local edit above; this was not checked further (no engine
rebuild). `run_reference.py` prints these differences on every run, for information.

## KI gaps (status 2026-10-06)

No KI tool fix for RHESSys has landed in this checkout since the case was made (last RHESSys commit `ed82315`), so every item below is still open.

- **Still open:** `tools/run_rhessys.py` puts `-of <filter>` right after `-r <flowtable>`. RHESSys reads the next
  word after the flow table as an optional surface flow table unless it is a known option, and
  `-of` is not in RHESSys's known-option list, so the engine stops with
  `option #22 is invalid`. Also `-of` cannot be used together with `-b` (RHESSys: "Both legacy
  and output filter output were specified"). So the KI tool cannot run filter output with a flow
  table. This case uses legacy output, which the tool runs fine.
- **Still open:** `tools/parse_output.py` legacy mode uses a fixed column list that does not match the header of
  this engine's `basin.daily` (the file has its own header row). It was not used; output is read
  directly by header names.
- **Still open:** The engine's output filter crashes on the official `testing_filter.yml` (see above).
