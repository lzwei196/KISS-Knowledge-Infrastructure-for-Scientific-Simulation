# DART — foundation test case: "lorenz63"

Authentic foundation case: the official **Lorenz-63** example that ships with DART
(`models/lorenz_63/work`). It is DART's own first-run check: a truth run makes
synthetic observations, then a 20-member ensemble filter (EAKF) assimilates them.
`inputs/` are the unmodified files from the DART git tree.

| | |
|---|---|
| Engine | DART v11.21.2 (NCAR, git 56fee97), programs `perfect_model_obs` and `filter` built for lorenz_63 |
| Source | NCAR/DART `models/lorenz_63/work/` |
| Licence | Apache-2.0 (DART) |
| KI | `DART` |

## Run
```
python run_reference.py    # finds the built programs (or $DART_WORK_DIR, --dart-work-dir); 0=PASS 2=FAIL 3=missing
```
It copies `inputs/` to a fresh temp dir, makes `perfect_input.nc` and `filter_input.nc`
with `ncgen`, then runs `perfect_model_obs` and `filter` through the KI's own
`tools/run_dart.py`.

## Expected (recorded 2026-10-05, deterministic: two clean runs were byte-identical)
- 600 obs in `obs_seq.out` and `obs_seq.final`; 46 copies in `obs_seq.final`
- RMSE against truth: obs 2.9035, prior ensemble mean 1.1085, posterior ensemble mean 0.8103
- mean spread: prior 0.7847, posterior 0.6324
- the filter must cut the error: posterior < prior < obs

The `obs_seq.out` / `obs_seq.final` that DART keeps in git were written by an older
DART version (old header, other noise draws), so they are not used as the reference.
A missing program or `ncgen` is reported (exit 3), never faked.
