# TELEMAC-MASCARET test case: gouttedo (water drop in a basin)

## What it is
The official TELEMAC-2D example `examples/telemac2d/gouttedo`. A drop of water
(a Gaussian bump on a flat 2.4 m water surface) is let go in a closed square basin
(20.1 m x 20.1 m, 4624 nodes, 8978 triangles). The waves spread out and bounce off
the walls. The run is 100 steps of 0.04 s (4 s), with output every 5 steps (21 records).
This package uses the main sequential run `t2d_gouttedo.cas` (the `seq` study in
the official `vnv_gouttedo.py`). Runs on 1 core in a few seconds.

## Source
- Repo: https://gitlab.pam-retd.fr/otm/telemac-mascaret (official TELEMAC-MASCARET repo)
- Commit: be14a12315ac9346ca0ce8da065aba5d0ec5766e (2026-03-26), version 9.1-dev
- Folder: `examples/telemac2d/gouttedo`. The `.slf` files are Git LFS objects; the
  copies here match the LFS sha256 ids in the git pointers.
- Licence: GNU GPL v3.0 (LICENSE.txt in the repo).

## Files
- `inputs/` unmodified official files: `t2d_gouttedo.cas` (steering file),
  `geo_gouttedo.slf` (mesh), `geo_gouttedo.cli` (boundary conditions),
  `user_fortran/user_condin_h.f` (makes the water drop), `user_fortran/user_condin_trac.f`.
- `reference/f2d_gouttedo.slf` the official reference result that ships with the example.
- `reference/vnv_gouttedo.py` the official validation script (holds the tolerance).

## Engine
telemac2d from the server build `builds/main_gfortran_release` of the repo above,
started by `scripts/python3/telemac2d.py`. Serial (1 rank). The user Fortran is
compiled with `f95` (gfortran 13.3) at run time, as TELEMAC always does.

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py [--hometel DIR] [--build-dir DIR]
```
TELEMAC lookup: `--hometel` -> `$HOMETEL` -> `which telemac2d.py` -> server default
(`/home/server/knowledge-dissection-toolkit/auto_dissect/_work/TELEMAC_MASCARET/source/repo`).
Build dir: `--build-dir` -> `$BUILD_DIR` -> `<hometel>/builds/main_gfortran_release`.
The script copies the inputs to a fresh temp dir, sets HOMETEL, BUILD_DIR, SYSTELCFG,
PYTHONPATH and LD_LIBRARY_PATH, runs the case through the KI tool `tools/run_telemac.py`
(TELEMAC's own temp work folder is put inside the temp dir with `-w`), reads the result
with the KI tool `tools/parse_selafin.py`, checks `expected.json`, and deletes the temp dir.
Exit 0 = PASS, 2 = checks failed, 3 = engine or compiler missing (nothing run).

## Expected results
- Official check (from `vnv_gouttedo.py`): for every variable (U, V, H) at the last
  record, max |run - f2d_gouttedo.slf| <= 1e-7. We also check all 21 records with the
  same limit (stricter than the official check).
- Values read from the official reference file, tolerance 1e-7: record count 21,
  end time 4 s, 4624 nodes, 8978 triangles, initial max depth 4.7732 m, max depth at
  2 s 3.0049 m, final max/min/mean depth 3.1281 / 2.1299 / 2.4723 m, final max U and
  min V +-0.4633 m/s.
- From our own run (no official value): initial and final water volume 999.7839 m3,
  cumulated relative volume error about 1.9e-15 (limit 1e-10).
- Finished normally: KI tool return code 0, status success, listing says `CORRECT END OF RUN`.

Result on 2026-10-05: last record matches the official reference exactly (difference 0);
largest difference over all records is 5.7e-14. Two runs gave bit-identical files.

## KI gaps (status 2026-10-06)
- **Fixed in `c54e9f0`:** `tools/run_telemac.py` now makes the `-Wl,--dependency-file` folders (from `build_commands.json`) in TELEMAC's work folder, so cases with a `FORTRAN FILE` link. Before: the user Fortran link stopped in `ld` because `CMakeFiles/user_fortran.dir` did not exist; `run_reference.py` makes that empty folder in its temp run dir and passes `-w wd` through `--options`.
  The workaround in `run_reference.py` is kept so the case also runs with older tool versions.
- **Partly fixed in `c54e9f0`:** the tool now sets HOMETEL, BUILD_DIR and LD_LIBRARY_PATH itself (server defaults if not given); still open: it does not set SYSTELCFG or PYTHONPATH. Before: it set none of SYSTELCFG, BUILD_DIR, PYTHONPATH or LD_LIBRARY_PATH; the caller had to (run_reference.py does).
- **Partly fixed in `c54e9f0`:** on failure the tool now returns the last 4000 characters (was 500) and adds hints for known errors; still open: to keep the full TELEMAC listing (`*.sortie`) you still need `--options "-s"`. Before: only the last 500 characters of stderr, which hid the real error.
