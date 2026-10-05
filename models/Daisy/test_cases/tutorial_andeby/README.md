# Daisy — foundation test case: "tutorial_andeby"

Authentic foundation case: the official Daisy tutorial setup `sample/test.dai`
("Simulation for use in tutorial.") from github.com/daisy-model/daisy
(commit a621e3b). `inputs/` are the unmodified `test.dai` and its weather file
`dk-taastrup.dwf`, taken with `git show HEAD:sample/...`.

The setup: a sandy Danish soil column ("Andeby farm", FAO3 sandy top soil over a
C horizon to 2.5 m, free drainage), daily Taastrup weather, 1986-12-01 to 1988-04-01.
Plowing, 100 kg mineral N, spring barley sown with grass under it, barley harvest,
80 kg N in autumn, grass cut. Runs in about 1 second.

| | |
|---|---|
| Engine | Daisy 7.1.4 `daisy` (server build) — the binary the KI preflight resolves |
| Library | Daisy `lib/` (`tillage.dai`, `crop.dai`, `log.dai` and what they load), found through `DAISYHOME` |
| Source | github.com/daisy-model/daisy, `sample/test.dai` + `sample/dk-taastrup.dwf`, commit a621e3b |
| Licence | GNU GPL v2 (repo `COPYING.txt`); repo also ships `COPYING.LIB` (LGPL v2.1) |
| KI | `Daisy` |

## Run
```
python run_reference.py    # 0=PASS 2=FAIL 3=missing
```
Binary: `--daisy-bin` -> `$DAISY_BIN` -> `which daisy` -> server default.
Library: `--daisy-home` -> `$DAISYHOME` -> `<binary dir>/../source/repo` -> server default.
The library is part of the Daisy install, so it is not copied into `inputs/`.

The script copies `inputs/` to a fresh temp dir, runs the case through the KI's own
`tools/run_daisy.py` (with `DAISYHOME` set), reads the `.dlf` logs with the KI's own
`tools/parse_daisy_output.py`, checks `expected.json`, then deletes the temp dir.
Use the python that has numpy + pandas (server: `/mnt/disk1/Hydrocraft_server/python_env/bin/python`).

## Expected
The Daisy repo ships **no reference output** for this tutorial setup, so the expected
values come from a clean run of the server binary on 2026-10-05. Two clean runs gave
identical `.dlf` and checkpoint files (only the `RUN:` time stamp differs), so the run
repeats exactly. Checks:

- run exit code 0 and `Program finished` in `daisy.log`; 6 `.dlf` logs written
- 2 harvest events; spring barley harvested 1987-08-26 (day 238)
- barley grain 2.70161 Mg DM/ha, stem 5.51912 Mg DM/ha, grain N 48.7602 kg N/ha
- grass cut leaf 1.43068 Mg DM/ha; barley peak LAI 5.28476; 488 daily crop rows
- precipitation 899.9 mm (same as the sum in `dk-taastrup.dwf` over the run period),
  actual ET 538.14 mm, matrix percolation 127.00 mm, final soil matrix water 675.30 mm
- matrix N leaching 6.317 kg N/ha, crop N uptake 232.72 kg N/ha
- Daisy's own 13 end-of-run N and water balance summaries in `daisy.log` all close
  (In - Out - Increase printed as 0.0 / 0.000)

Side note (not part of this case): the repo's own test suite
(`test/dai-system-tests`) has baseline files for other, smaller setups. As a quick
check of the binary, `crop-simple` reproduced its baseline byte-for-byte and
`groundwater-deep` matched to about 6 significant figures (baseline made with 7.0.13).

## KI gaps (status 2026-10-06)
- **Fixed in `13717b9`:** `tools/run_daisy.py` now sets `DAISYHOME` to the Daisy library when the
  caller set none (also `--daisy-home` and `DAISY_BIN`), and exits 1 when the engine fails.
  Before: with no `DAISYHOME`, Daisy could not open `tillage.dai`, `crop.dai`, `log.dai` and
  stopped with "Unknown 'action' model 'plowing'"; this case works around it by setting
  `DAISYHOME` in the environment it passes to the tool. The workaround in `run_reference.py` is
  kept so the case also runs with older tool versions.
- **Still open:** The KI has converters only for weather (`convert_weather_to_dwf.py`) and soil
  (`convert_soil_to_dai.py`); the main `.dai` (crop and management) has no builder tool,
  so this case uses the official `.dai` as is.
