# SWAT+ case: Xixian 息县 (gauge 50225601, upper Huai River)

The input deck behind `tools/calib_run.py` (`BASE_DECK`), cleaned so it can sit on a
Windows disk, plus the gauge record and the expected outputs.

- `inputs/TxtInOut/`: 251 input files (33-station CMFD weather, 78 HRUs, 33 channels).
  Simulation 1979-1990, printed output from 1981 (`print.prt` nyskip 2).
  `calibration.cal` is an input (named on the `chg` line of `file.cio`) and is kept.
- `inputs/obs/xixian_50225601.txt`: daily record for station 50225601, 1951-2024
  (columns stcd, dates, z, Q). Server source: `china_water_level/淮河txt/息县.txt`.
- `expected/`: outputs of the server run (SWAT+ rev59 Linux build). `channel_day.txt` is
  114 MB, so only its SHA-256 and size are given.

## What was cleaned, and the check

The server deck also held `STA01.pcp/.tmp/.slr/.hmd/.wnd` next to `sta01.*`. On Windows
those names are the same file. Every file in the deck names the lowercase `sta01.*`;
the uppercase files are an older weather set for another station (`p000001`) that
nothing reads. They are left out.

Check on 2026-11-11 with the same binary: the deck with and without the uppercase files
gave byte-identical outputs, and both match the stored server run of 2026-07-20
(`basin_wb_yr.txt`, `channel_day.txt`, `crop_yld_aa.out`, `diagnostics.out`,
`files_out.out`). A rerun from these exact files gave the same `channel_day.txt` hash.

## Known gaps

- `file.cio` names `hmet_water.ini` and `soils-lte.sol`, which are not in the deck. They
  were also absent in the stored server run, so this result does not use them. A different
  SWAT+ build may treat a missing file differently; check on the desktop build.
- The binary is not included. A Windows build or another revision may not give the same
  numbers; compare against `expected/` first.

Hashes of every file are in `SHA256SUMS`.
