# SWAP foundation test case: Hupselbrook

## What it is

SWAP's own official test case, `tests/cases/1.hupselbrook`, from the SWAP git
repository (Wageningen). It is a 3-year (2002-2004) field run for the Hupselse
Beek site in the Netherlands (project `hupsel`):

- 200 cm soil profile, soil water flow, root water uptake
- crops: maize (2002), potato (2003), grass (2004)
- one fixed irrigation (5 mm on 2002-01-05)
- drainage to one drain system (`swap.dra`)
- heat and solute transport switched on

It runs in under a second.

## Source

- Repo: https://github.com/SWAP-model/swap
- Folder: `tests/cases/1.hupselbrook`
- Commit: `7587ca3a5f037a7276f1c86059632f921f710775` (2026-01-08), SWAP version 4.2.0
- Licence: LGPL-2.1 (see the SWAP repo `LICENSE` / README)

`inputs/` holds the unmodified files, taken with `git show HEAD:<path>` so no
local run output is mixed in:

| file | what |
|---|---|
| `swap_linux.swp.template` | main input file (paths use `./`) |
| `283.met` | daily weather 2002-2004 |
| `maizes.crp`, `potatod.crp`, `grassd.crp` | crop files |
| `swap.dra` | drainage file |

The only step besides copying is the same one SWAP's own test task does
(`pixi.toml`, task `test-linux`): copy `swap_linux.swp.template` to `swap.swp`.
No input file is changed.

## Engine

- SWAP 4.2.0, built on this server from the commit above with Meson + gfortran
  (`builddir/swap`, sha256 `a696efc5344daa53b3ddeebd3664656d0822959a5b2f4f863efc710469f1cf97`).
- The server checkout has one local change in `meson.build` only: it adds
  gfortran compile flags for Linux (`-O2 -ffree-line-length-none -std=legacy`
  and warning switches). No Fortran source is changed.
- SWAP ends a good run with exit code 100 and prints `Swap normal completion!`;
  it also writes `swap.ok` ("simulation succesfully terminated").

## How to run

```
python run_reference.py [--swap-bin /path/to/swap]
```

Binary lookup: `--swap-bin` -> `$SWAP_BIN` -> `which swap` -> server default
path. The script copies `inputs/` to a fresh temp dir, makes `swap.swp`, runs
the KI tool `tools/run_swap.py`, reads the output with the KI tool
`tools/parse_swap_output.py`, checks `expected.json`, and deletes the temp dir.

Exit codes: 0 PASS, 2 a check failed, 3 engine or dependency missing
(prints `MISSING DEPENDENCY: ... NOT run.`). Needs Python with numpy.

## Expected results

This case ships **no reference output** in git. SWAP's own CI test only checks
that the run finishes normally. So the numbers in `expected.json` come from
real runs on this server. Two clean runs gave byte-identical `result.blc`,
`result.inc`, `result.vap` and `result.sba`, so the model is deterministic here.
(The untracked `result.*` files left in the server's copy of the folder from
an earlier local run also match byte for byte, apart from the time stamp line.)

Checks (3 years total unless said):

| check | value |
|---|---|
| finished normally | run tool success + `swap.ok` success line |
| yearly balance blocks / monthly rows / profile snapshots | 3 / 36 / 37 |
| soil water at start / end | 71.60 / 73.05 cm |
| rain / irrigation | 236.71 / 0.50 cm |
| interception / transpiration / soil evaporation | 10.65 / 99.67 / 51.92 cm |
| drainage | 73.51 cm |
| largest yearly water balance error | 0.00 cm |
| groundwater level min / max / mean (month ends) | -146.0 / -42.2 / -91.54 cm |

Tolerances only cover print rounding (0.01-0.02 cm for `.blc` values, 0.1 cm
for groundwater level).

## KI gaps (status 2026-10-06)

No KI tool fix for SWAP has landed in this checkout since the case was made (last SWAP commit `f54c86b`), so every item below is still open.

- **Still open:** The KISS copy of `tools/run_swap.py` has a placeholder pinned binary path
  (`KISSPATH_INTERNAL_NOT_SHIPPED/...`), so it cannot run without `--binary`.
  This script always passes `--binary <found swap> --allow-unpinned-binary`.
- **Still open:** The KISS copy of `tools/run_swap.py` is older than the live server copy: it
  calls `swap` with no file argument (fine here, SWAP then reads `swap.swp`),
  and it counts exit code 0 or any `*.ok` file as success, while the live copy
  needs SWAP's own `Swap normal completion` line. To be safe this script also
  checks that the fresh `swap.ok` holds SWAP's success line.
- **Still open:** The KI's `assemble_swap_config.py` builds a new `.swp` from a base template;
  it is not used here because the official case already has its own `.swp`.
