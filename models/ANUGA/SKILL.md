# ANUGA Skill

**Type:** 2D depth-averaged shallow-water hydrodynamics (finite-volume, unstructured triangular mesh)
**Primary use:** tsunami inundation, dam-break, flood modeling
**Authoritative source:** https://github.com/anuga-community/anuga_core
**Installed at:** /home/server/.local/lib/python3.12/site-packages/anuga

## Validation strategy

ANUGA is a physics solver, not a forecasting model. The correct validation is against
**analytical / closed-form solutions**, not gauge NSE/KGE. Treat `comparison_type='analytical'`
as the default mode for ANUGA tests.

Standard benchmarks shipped under `validation_tests/analytical_exact/` in the source repo:

| Test | Analytical reference | Use |
|------|----------------------|-----|
| `dam_break_wet` | Stoker / Ritter (Riemann) | quick wet-bed dam-break benchmark (default) |
| `dam_break_dry` | Ritter | dry-bed benchmark |
| `carrier_greenspan_transient` | Carrier & Greenspan 1958 | canonical linear-slope runup |
| `parabolic_basin` | Thacker 1981 | oscillating parabolic basin |
| `runup_on_beach` | steady-state flat lake | smoke test |

## Default test

`dam_break_wet`: 1D Stoker dam-break on a 1000 m x 5 m flat channel, h1=10 m (left),
h0=1 m (right), no friction, finaltime=50 s. Compare modeled stage along the centerline
at t=50 s against `anuga.validation_tests.analytical_exact.dam_break_wet.analytical_dam_break_wet.vec_dam_break`.

## Execution

```
python -c "import anuga" # sanity
# runner: diagnostics/run_dam_break_wet.py — loads numerical + analytical, writes NSE/R/KGE
```

Metric reporting: NSE, Pearson R, KGE computed on 1D centerline stage profile
(numerical_stage at t_final vs analytical h at the same x).

## Notes on previous failure

The earlier run used `examples/simple_examples/runup.py` (synthetic 10x10 rectangular beach)
with `comparison_type='none'`, yielding null metrics. The fix is to switch to an
analytical-solution benchmark and compare pointwise.
