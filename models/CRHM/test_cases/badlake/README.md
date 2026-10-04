# CRHM — foundation test case: "Bad Lake"

This is the CRHM KI's **foundation test case**: one authentic, complete, runnable
example that proves the real engine and this KI's input/output contract work end
to end. It is the canonical **Bad Lake** (Saskatchewan) project from the CRHMcode
distribution's own `system_regression_test` suite — nothing here is synthetic.

## What it is

| | |
|---|---|
| Engine | **CRHM** (Cold Regions Hydrological Model), CRHMcode CLI, binary `crhm`, installed build **v4.7_16** |
| Source | Centre for Hydrology, University of Saskatchewan (CRHMcode); project from its `system_regression_test` suite |
| Licence | GPL — see `COPYING.txt` in the CRHMcode distribution |
| Case | `badlake` — Bad Lake, Saskatchewan, 3 HRUs |
| Simulation | 1973-01-01 → 1976-01-01 (hourly) |
| KI | `CRHM` in `KISS-Knowledge-Infrastructure-for-Scientific-Simulation` |

## Files (paths relative to this folder)

```
test_cases/badlake/
├── README.md
├── manifest.json      # input files with size + sha256
├── inputs/
│   ├── badlake.prj                      # CRHM project (references prj/BadLake/Badlake73_76.obs)
│   └── prj/BadLake/Badlake73_76.obs     # observation forcing, at the path the prj expects
├── run_reference.py   # runs crhm in a clean temp dir and checks expected.json
└── expected.json      # authentic results pinned to the installed v4.7_16 build
```

The large model output (~42 MB) is **not** committed — it is reproducible. It is
anchored in `expected.json` by line count, timestamps, two spot values, and the
full-output sha256 of the installed build.

## How to run it

The prj reads its observation file by the relative path `prj/BadLake/Badlake73_76.obs`,
so run from a directory laid out like `inputs/`:
```
crhm badlake.prj -o badlake_output.txt
```
Or let the reference runner do it in a throwaway temp dir:
```
python run_reference.py            # auto-finds crhm (or $CRHM_BIN, or --crhm-bin)
```
Exit `0` = PASS, `2` = checks failed, `3` = the `crhm` binary was not found
(reported explicitly; the case is not marked passed when it did not run).

## Engine / build

Installed at `/mnt/disk1/Hydrocraft_server/model/crhmcode/crhmcode/build/crhm`
(v4.7_16). Set `CRHM_BIN` or pass `--crhm-bin` for another build.

## Expected results (authentic, recorded 2026-10-04)

- Run completes; output spans 1973-01-01T01:00 → 1976-01-01T00:00 (26,282 lines).
- Final timestep: basinflow(1) ≈ 0.07, basingw(1) ≈ 0.046.
- Full output of the installed build has sha256
  `f75f41db2e4cda5cf96356c8aff7054fd8e395d3c8c001cd5a5887f73ed2c4e8` (deterministic:
  two runs are byte-identical).

## Honest note on the distribution's shipped expected_output

The CRHMcode distribution ships
`system_regression_test/expected_output/badlake_output.txt`. On this server it has
the **same** 26,282 lines, timestamps and column header, but ~26,250 data rows
**differ numerically** from the installed `crhm` v4.7_16 — i.e. the shipped
expected was produced by a different CRHM build. This test therefore pins the
**installed** engine (which it reproduces exactly) and does **not** assert a match
against the shipped file. If the engine is rebuilt, re-record `expected.json` from
the new build.
