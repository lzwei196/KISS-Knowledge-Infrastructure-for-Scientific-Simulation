# DHSVM — foundation test case: "chiwawa"

**Data:** the input data (3.66 GB) is not in git. It is in the Baidu Netdisk pack
`/KISS_test_case_packs/DHSVM/chiwawa_v1` (version v1, 370 files).
If the data is not on your machine, `run_reference.py` downloads it from
**https://pan.baidu.com/s/1ksx24w8Uz4XfO2Fy1KjDwQ (code `upbs`)**; or download it by hand
and pass `--pack-dir <folder>`.

Authentic foundation case: the official **Chiwawa** test case that ships with DHSVM
(`TestCase/Chiwawa` in the DHSVM-PNNL repo), run with its own baseline config
`INPUT.Chiwawa.Baseline`, unchanged. Chiwawa River basin, Washington, USA: 425 x 300 grid
at 90 m (55 046 active pixels), 3-hour step, one water year 10/01/1970 to 10/01/1971,
Livneh gridded weather, network channel routing.

| | |
|---|---|
| Engine | DHSVM Version 3.2 (PNNL), git e6f333d0e70ed72345d52f1ab83e35317fa92458 (2022-07-21) |
| Source | https://github.com/pnnl/DHSVM-PNNL `TestCase/Chiwawa` |
| Licence | the repo has no LICENSE file; DHSVM is given out openly by PNNL / Univ. of Washington (https://dhsvm.pnnl.gov) |
| KI | `DHSVM` (run tool `tools/run_dhsvm.py`) |
| Run time | about 2-3 minutes, one core |

## The data pack (DHSVM/chiwawa_v1)
Made with `git archive HEAD TestCase/Chiwawa` from the repo, so every file is the
official tracked file (local leftovers such as extra INPUT.* files, modelstate from other
dates and old output/ are left out). Contents:
`INPUT.Chiwawa.Baseline`, `input/` (DEM, mask, soil, veg, stream network, shading maps),
`modelstate/` (start state 10/01/1970), `LivnehForcing/` (320 grid-cell weather files,
1950-2013), plus `PACK_MANIFEST.json`.
`manifest.json` → `pack.files` lists every file with bytes + sha256.

| | |
|---|---|
| Netdisk folder | `/KISS_test_case_packs/DHSVM/chiwawa_v1` |
| Share link | https://pan.baidu.com/s/1ksx24w8Uz4XfO2Fy1KjDwQ  code `upbs` (no expiry) |
| Server copy | `/home/server/ki_test_case_packs/DHSVM/chiwawa_v1` |
| Size | 3 663 030 492 bytes, 370 files |

## Run
```
python run_reference.py                  # 0=PASS 2=checks failed 3=engine or data missing/bad
python run_reference.py --pack-dir /path/to/chiwawa_v1
```
Where the data is looked for, in order: `--pack-dir` → `$DHSVM_PACK_DIR` → the server copy →
the cache `~/.cache/kiss_packs/DHSVM/chiwawa_v1` (or `--cache-dir` / `$KISS_PACK_CACHE`) →
download from the share link into that cache. `--no-server-pack` (or `KISS_NO_SERVER_PACK=1`)
skips the server copy; `--no-download` never downloads.
Before any run, **every file is checked against manifest.json (bytes + sha256)**. A missing
or changed file, or a failed download, stops with exit 3 `MISSING/BAD DATA ... NOT run.`

The download needs a logged-in Baidu account (Baidu does not let anyone download a share
without login): set `KISS_BAIDU_COOKIES="BDUSS=...; STOKEN=..."` (cookies from a browser
logged in to pan.baidu.com), or have BaiduPCS-Py logged in. Downloads go direct (no proxy).
After many downloads in a short time Baidu may ask for a captcha (error -20); the script
waits and retries a few times, then stops with exit 3. Files already fetched stay in the
cache, so running it again later resumes the download.
Note: all files in this pack are small (the biggest is about 13 MB), so they all come
straight from the share link; no BaiduPCS-Py step is needed. (Baidu gave no plain share link
for a 54.6 MB file in the tRIBS pack; for such files the script falls back to BaiduPCS-Py.)

Binary lookup: `--dhsvm-bin` → `$DHSVM_BIN` → `which DHSVM` → server default.

How the run is laid out: the config names its files as `../../TestCase/Chiwawa/...`, so the
temp dir gets `TestCase/Chiwawa/` (input/ and modelstate/ copied, LivnehForcing/ linked
read-only to the pack, empty output/ made because the repo does not ship it) and the config
goes in `run/case/`, two levels down. Nothing in any input file is changed.

## Expected (recorded 2026-10-06; two clean runs gave byte-identical output files)
- exit 0 and DHSVM's own line `END OF MODEL RUN`
- 2920 three-hour steps in `Streamflow.Only`
- Mass.Final.Balance (mm): inflow 1566.438, precip 1575.694, outflow 1469.245, ET 174.350,
  to channels 1294.895, storage change 97.157, final snow 137.985, final soil water 344.184,
  **mass error -0.036 mm** for the year
- outlet flow (m3 per 3-h step): mean 197 717, peak 3 140 400, last 73 709
- peak basin-mean snow water 1.45061 m; no NaN/Inf in any output

The repo ships no reference outputs for Chiwawa, so these values come from our own runs.
The official period is one year and runs in ~2 minutes, so nothing was shortened.

## Known KI gaps
- `tools/run_dhsvm.py` scans the whole log for the plain text `nan|inf` and so flags the
  normal line "Summary **inf**o on met stations ..." as "NaN or Inf detected". The run is
  fine (the output files hold no NaN/Inf, checked by `nan_inf_tokens_in_outputs`).
  `run_reference.py` prints the flag but does not fail on it.
