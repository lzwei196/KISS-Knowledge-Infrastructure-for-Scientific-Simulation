# ADCIRC — foundation test case: "quarterannular_2d"

Authentic foundation case: the official ADCIRC test-suite case
`adcirc/adcirc_quarterannular-2d` (github.com/adcirc/adcirc-testsuite, commit 72bb573).
Quarter-annulus grid (63 nodes, 96 elements), 5-day tidal run. `inputs/` are the
unmodified `fort.14` (grid) and `fort.15` (run control).

| | |
|---|---|
| Engine | ADCIRC serial `adcirc` (server build) — the binary the KI preflight resolves |
| Source | ADCIRC test suite, `adcirc/adcirc_quarterannular-2d` |
| KI | `ADCIRC` |

## Run
```
python run_reference.py    # finds adcirc (or $ADCIRC_BIN, --adcirc-bin); 0=PASS 2=FAIL 3=missing
```
It runs the case through the KI's own `tools/run_adcirc.py` (serial) in a fresh temp dir.

## Expected
The expected values come from the **official solution files** of the ADCIRC test suite
(`control/`, Git LFS), with the suite's own tolerance 1e-5:
824 output snapshots to t = 431749.6 s, global elevation max 0.6546 m / min −0.6345 m,
max speed 0.2969 m/s, station elevation max 0.5773 m / min −0.5505 m,
peak water level (maxele) max 0.6549 m.

A clean run of the server binary on 2026-10-05 matched the official solution:
max difference fort.61 1.3e-8, fort.62 7.6e-9, fort.63 1e-14, fort.64 1e-12,
maxele.63 byte-identical. (fort.54 and maxvel.63 differ only in the phase or
time-of-peak of near-zero values, which carry no meaning.)
