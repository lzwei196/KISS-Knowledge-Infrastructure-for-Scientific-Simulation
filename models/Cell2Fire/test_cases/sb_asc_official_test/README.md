# Cell2Fire — foundation test case: "sb_asc_official_test"

Official foundation case: the **sb-asc** case from Cell2Fire W's own test suite
(`test/model/sb-asc`, run by `test/test.sh`). It uses the Scott & Burgan fire model on a
small 7 x 7 grid (100 m cells) where each cell holds a different Scott & Burgan fuel type,
so one small run touches almost every fuel model. It runs 113 fires with seed 123 and
compares the result with the official target results that ship in the repo.
`inputs/` are the unmodified files from git HEAD of the repo.

| | |
|---|---|
| Engine | Cell2Fire W (C2F-W), built from fire2a/C2F-W git 38ff0a0 (2026-03-02); the local build prints `version: v0.0.0` |
| Source | https://github.com/fire2a/C2F-W — `test/model/sb-asc/` (inputs) and `test/target_results.zip` (official results) |
| Licence | GPL-3.0 (C2F-W) |
| KI | `Cell2Fire` |

Files:
- `inputs/fuels.asc` — 7 x 7 fuel map (Scott & Burgan codes; 6 cells cannot burn: 0, 91, 92, 93, 98, 99)
- `inputs/Weather.csv` — 5 hourly weather rows (WS 10, WD 180)
- `inputs/spain_lookup_table.csv` — fuel code table
- `reference/target_results.zip` — the official target results, unmodified copy of
  `test/target_results.zip` (holds all 8 test cases; only `target_results/sb-asc` is used)

## Run
```
python run_reference.py    # finds the engine: --cell2fire-bin -> $CELL2FIRE_BIN -> which Cell2Fire -> server path
                           # exit 0=PASS 2=FAIL 3=engine missing
```
It copies `inputs/` into a fresh temp dir as `model/sb-asc/` and runs the exact official
command (same folder names as `test/test.sh`, so the log text matches):
```
Cell2Fire --input-instance-folder model/sb-asc --output-folder test_results/sb-asc \
  --nsims 113 --output-messages --grids --out-intensity --sim S --seed 123 --ignitionsLog --scenario 1
```
Like the official test, it then removes the `version:` line from the log and compares
every output file byte for byte with the official target. Run time is under a second.
`--print-metrics DIR` prints the checked numbers for any output folder.

The seed is fixed at 123 as in the official command. With it, the run repeats exactly:
two runs on this server both matched all 753 official target files byte for byte.

## Expected (all values read from the official target files, recorded 2026-10-05)
- every one of the 753 output files equals the official target (official rule: exact match)
- 113 fires finish; 113 message files, 113 intensity grids, 113 grid folders, 113 ignition rows
- 6 cells cannot burn; burnt cells per fire: mean 41.938, min 28, max 43
- 4782 spread events in total; last spread at fire period 298
- burn probability over the 49 cells: mean 0.85588, max 1.0
- surface fire intensity: max 41063.4, mean 5707.26 (all cells, all fires)
- for every fire, ignition cell + cells reached by spread messages = the Burnt count the model prints

Note: the `Grids/GridsN/ForestGridNNN.csv` files from `--grids` are snapshots at set
times, not the final burn scar, so burnt cells are counted from the spread messages.

## Known KI gaps
- `tools/run_cell2fire.py` cannot run this case. It stops with "No elevation.asc or
  elevation.tif found", but the engine does not need elevation (it fills it with NaN, as
  the official log shows). It also always adds `--fmc`, `--weather rows`, `--final-grid`,
  `--Fire-Period-Length`, `--Weather-Period-Length`, `--ROS-CV` and `--nthreads`, with no
  way to leave them out, so it cannot give the exact official command. The engine is run
  directly here.
- `tools/parse_cell2fire_output.py` does not read this output: it looks for
  `MessagesFile{n}.csv` / `{n:02d}` (the engine writes 3-digit names such as
  `MessagesFile001.csv` when there are 100+ fires, so it found only fires 100-113),
  `Grids/GridsN/FinalGrid.csv` (the engine writes `ForestGridNNN.csv`) and
  `Intensity/IntensityFile{n}.csv` (the engine writes `SurfaceIntensity/SurfaceIntensityNNN.asc`),
  then it crashes when printing the summary (`Unknown format code 'f'`). The output is
  read directly here.
