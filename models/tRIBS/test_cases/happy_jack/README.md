# tRIBS — foundation test case: "happy_jack"

**Data:** the benchmark data (237 MB) is not in git. It is in the Baidu Netdisk pack
`/KISS_test_case_packs/tRIBS/happy_jack_v1` (version v1, 102 files).
If the data is not on your machine, `run_reference.py` downloads it from
**https://pan.baidu.com/s/1-7fewTfk2tuJxLJfKzR3wA (code `8ncs`)**; or download it by hand
and pass `--pack-dir <folder>`.

Authentic foundation case: the official **Happy Jack** benchmark of tRIBS (SNOTEL
point-scale run at Happy Jack, Arizona, USA), published on Zenodo (record 10909507,
DOI 10.5281/zenodo.10909507) and fetched by the tRIBS repo's own
`testing/black_box/setup_black_box.sh`. It is run with its own `src/in_files/happy_jack.in`,
unchanged: start 06/01/2002, 143 183 hours (~16.3 years), hourly weather and rain.
It is checked with the tRIBS repo's own black-box tests.

| | |
|---|---|
| Engine | tRIBS Version 5.3.0 (Summer 2025), git 813aad5560a72c7529f8b6a5035a67c20f6a6fa0, serial build |
| Source | data: https://zenodo.org/records/10909507 (`happy_jack.gz`); tests: https://github.com/tribshms/tRIBS `testing/black_box/` |
| Licence | data CC-BY-4.0 (Zenodo); tRIBS code and tests MIT |
| KI | `tRIBS` (run tool `tools/run_tribs.py`) |
| Run time | about 15 seconds |

## The data pack (tRIBS/happy_jack_v1)
`happy_jack.gz` from Zenodo (52 672 057 bytes, md5 346b1826fe2311a30b3630162b028b8b =
the md5 Zenodo lists) unpacked as is (`tar -xzf --strip-components=1`), nothing added or
changed, the macOS `._*` side files included. Contents: `src/in_files/happy_jack.in`,
`data/` (DEM, soil and veg tables and maps, weather and rain 2002-2018, SNOTEL record,
dynamic veg maps, node lists), `results/reference.zip` (official reference output), `doc/`,
`README.html`, plus `PACK_MANIFEST.json`. The local leftovers on the server
(`results/ref_extract/`, `results/test/` outputs) are not in the pack.
`manifest.json` → `pack.files` lists every file with bytes + sha256.

| | |
|---|---|
| Netdisk folder | `/KISS_test_case_packs/tRIBS/happy_jack_v1` |
| Share link | https://pan.baidu.com/s/1-7fewTfk2tuJxLJfKzR3wA  code `8ncs` (no expiry) |
| Server copy | `/home/server/ki_test_case_packs/tRIBS/happy_jack_v1` |
| Size | 236 838 317 bytes, 102 files |

`inputs/happy_jack_pytest/` (in git, small) holds the official black-box test files from the
tRIBS repo, unchanged: `test_happy_jack.py`, `conftest.py`, the black-box `README.md`
(as `BLACK_BOX_README.md`) and `setup_black_box.sh`.

## Run
```
python run_reference.py                  # 0=PASS 2=checks failed 3=engine/dependency or data missing/bad
python run_reference.py --pack-dir /path/to/happy_jack_v1
```
Use a Python that has pytRIBS, numpy and pandas (server: `/mnt/disk1/Hydrocraft_server/python_env/bin/python`).
Where the data is looked for, in order: `--pack-dir` → `$TRIBS_PACK_DIR` → the server copy →
the cache `~/.cache/kiss_packs/tRIBS/happy_jack_v1` (or `--cache-dir` / `$KISS_PACK_CACHE`) →
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
One file, `results/reference.zip` (54.6 MB), gets no plain share link from Baidu (seen
2026-10-06: Baidu returns an encoded answer for it, while all files up to 13 MB work). For it the script needs
BaiduPCS-Py logged in: if the account already holds the pack folder (the owner), it downloads
that copy; otherwise it saves the file from the share into `/_kiss_pack_tmp/` of the account,
downloads it and deletes the temp copy.
Tested on 2026-10-06 only with the owner account (the own-copy branch). The save-from-share
branch for other accounts could not be tested here, because Baidu does not let the owner save
their own share; if it fails, the script stops with exit 3 and you can download the pack by hand.

Binary lookup: `--tribs-bin` → `$TRIBS_BIN` → `which tRIBS` → server default.
The run: `data/` and `src/` are copied to a fresh temp dir, the empty `results/test/` folder
(OUTFILENAME) is made, and tRIBS runs there through the KI's `tools/run_tribs.py`.

## Expected (recorded 2026-10-06; two clean runs gave byte-identical output files)
Official check (the tRIBS black-box way): the 9 tests of `test_happy_jack.py` are called on
the finished run, fed exactly like the official `conftest.py` does (same files), but without
conftest's own `m.run()` because the KI tool already ran the model. All 9 must pass:
- 7 forcing tests: rain, pressure, humidity, sky cover, wind, air temp and sunlight recorded
  in the output equal the input (official tolerances)
- water balance: |P - losses - change in storage| < 10 mm/yr — this run gives **7.249 mm/yr**
- snow: KGE of daily SWE vs the SNOTEL record > 1 - √2 = -0.414 — this run gives **-0.0847**

Plus numbers in `expected.json`: total rain 11 603.01 mm (**equal to the official
reference output** `reference.zip/hj_ref0.pixel`), ET 3359.20 mm, surface runoff 7951.01 mm (sum of `Srf_Hour_mm`, the column the official water-balance test uses),
peak SWE 61.75 cm, mean SWE 5.663 cm, final water table 10 665.10 mm, final unsaturated
moisture 1472.22 mm, 143 183 hourly records.

The official `reference.zip` was made in March 2024 with an older tRIBS. Today's tRIBS 5.3.0
adds an output column and gives somewhat different states (peak SWE 61.75 vs 54.92 cm, SWE
correlation 0.96, ET 3359 vs 3406 mm), so it is not a bit-for-bit target (the official tests
do not use it either). The script prints this comparison as information only.

Note on the official snow test (kept unchanged, as shipped): `test_model_efficiency` makes
`swe_cm` from the SNOTEL inches but then compares the model's `SnWE_cm` (cm) with the SNOTEL
`swe` column (inches). So the KGE value -0.0847 is the official test's own number with this
unit mix, not a clean cm-vs-cm skill score.

## Known KI gaps
- None found for this case. (Small note: `tools/run_tribs.py` checks the folders named in the
  .in file against the folder it is started from, not `--work-dir`; `run_reference.py` starts
  it from the run folder, so this does not matter here.)
