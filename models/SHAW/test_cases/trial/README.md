# SHAW — foundation test case: "Trial"

This is the SHAW KI's **foundation test case**: one authentic, complete, runnable
example that proves the real engine and this KI's input/output contract work
end to end. It is the official demo shipped with the SHAW model distribution —
nothing here is synthetic.

## What it is

| | |
|---|---|
| Engine | **SHAW 3.0.3** (Simultaneous Heat And Water model), binary `shaw303` |
| Source | USDA-ARS Northwest Watershed Research Center (G.N. Flerchinger); distribution archive `Shaw303.zip` |
| Licence | USDA-ARS public release (US Government work) |
| Case | `Trial` — the demo bundled with SHAW 3.0.3 |
| Simulation | Julian day 338 → 350, 1986 (a 13-day run) |
| KI | `SHAW` in `KISS-Knowledge-Infrastructure-for-Scientific-Simulation` |

## Files (all paths relative to this folder)

```
test_cases/trial/
├── README.md          # this file
├── manifest.json      # every input file with size + sha256
├── inputs/
│   ├── Trial.303.inp  # run control: I/O filenames, flags, simulation period
│   ├── Trial.30.sit   # site + soil parameters
│   ├── Trial.30.wea   # weather forcing
│   ├── Trial.moi      # initial soil moisture
│   └── Trial.tem      # initial soil temperature
├── run_reference.py   # runs the case in a clean temp dir and checks expected.json
└── expected.json      # authentic expected results (period, output structure, numeric checks)
```

The input files are the unmodified `Trial.*` files from the SHAW 3.0.3
distribution. Their checksums are in `manifest.json`; verify with:
```
python - <<'PY'
import json,hashlib,os
m=json.load(open('manifest.json'))
for rel,meta in m['files'].items():
    h=hashlib.sha256(open(rel,'rb').read()).hexdigest()
    print('OK' if h==meta['sha256'] else 'MISMATCH', rel)
PY
```

## How to run it

The engine prompts for the control-file name, then for a final Enter. In a clean
directory holding the five `inputs/` files:
```
printf 'Trial.303.inp\n\n' | shaw303
```
It writes `out.out`, `temp.out`, `moist.out`, `water.out`, `frost.out`,
`energy.out`, … to that directory.

The reference runner does this for you in a throwaway temp directory and checks
the result:
```
python run_reference.py                 # auto-finds shaw303 (or $SHAW_BIN, or --shaw-bin)
```
Exit code `0` = PASS, `2` = checks failed, `3` = the `shaw303` binary was not
found (reported explicitly — the case is **not** marked passed when it did not run).

## Engine / build

`shaw303` is built from the SHAW 3.0.3 Fortran source (`Shaw303.zip`,
`compile.sh`). On the build server it lives at
`/mnt/disk1/Hydrocraft_server/model/shaw/shaw303`. Set `SHAW_BIN` or pass
`--shaw-bin` to point `run_reference.py` at another build.

## Expected results (authentic, recorded from a clean run on 2026-10-04)

- Simulation completes JD 338→350, 1986 ("Run Complete").
- Output files present with the line counts in `expected.json`.
- Water balance, final day (JD 350): cumulative ET ≈ 4.0 mm; mass-balance error ≈ 0.0 mm.
- Snow, final day (JD 350, hr 24): depth ≈ 4.5 cm; SWE ≈ 9.2 mm.

Checks use tolerances so a correct build on another machine still passes; the
output-file sha256 in `expected.json` are informational only (SHAW's
floating-point output varies slightly by platform/compiler).
