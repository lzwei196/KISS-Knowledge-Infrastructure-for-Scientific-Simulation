# s3 Model execution (real engine)

## Purpose
Run EPA WASP 8.5 (`C:\WASP8\wasp\bin\waspccli.exe`) headless under WINE and extract results with
EPA's `BMD2_Extract.exe`. `tools/run_wasp.py` is the analytic SURROGATE and is not used here.

## Inputs
- a `.wif` (from s2 or an EPA example)
- engine discovery: `--wineprefix` → `$WASP_WINEPREFIX` → `KISSPATH_HOME/engine_builds_20261006/wasp/wineprefix`;
  wine: `--wine` → `$WASP_WINE` → PATH. Launcher in the models DB: `KISSPATH_HOME/engine_builds_20261006/wasp/run_wasp.sh`.

## Outputs
`<run-dir>/<model>.OUT` (setup echo + statistics), `<model>.BMD2` (results), `<model>_Flux.BMD2`,
`<model>_extract.csv` (Date_Time, Segment, one column per variable), `wasp_engine_summary.json`.

## Procedure
```bash
python tools/run_wasp_engine.py --wif case/erie_cb_surface.wif --run-dir run \
    --extract "Dissolved Oxygen" --extract "Water Temperature" --segments 1
python tools/run_wasp_engine.py --list-variables run/erie_cb_surface.BMD2
```
Exit codes: 0 ok; 1 run or extraction failed; 2 bad command line; 3 WINE/engine missing.

## Verification
Success needs ALL of: close-out line "run successfully closed out", fresh `.OUT` and `.BMD2`,
valid BMD2 header, no ERROR line other than the known "Failed to locate time function". The wine
exit code is ignored (2 on good runs, dt_wasp_032). Regression test after any change:
```bash
python test_cases/steady_state/run_reference.py     # EPA Steady State example, exit 0 = PASS
```
2026-10-07: PASS, 3.4 s, DO final seg 1 = 7.234781, seg 9 = 5.7412233 (same as the 2026-10-06 build).

## Traps
- A physically impossible deck can make waspccli spin forever; the tool stops it at `--timeout`
  (default 900 s) and kills only its own WINE session (dt_wasp_033).
- 31 "Failed to locate time function" lines are expected for decks built from the 2017 example
  (dt_wasp_034).
- The BMD2 holds about 48 records per day whatever the print interval (dt_wasp_039): extract only
  the variables and segments you need.
- Runtime: about 2.6 s per simulated year for the 10-box lake case (28 s for 11 years).

## Example
`outputs/wasp_lake_erie_central_real_engine/run/` (192,865 output times, 10 segments, 9 variables).
