# CMFD all-variable live subset test — 2026-09-14

Scope: catalogue product `cmfd_china_daily_010`, bbox `[115,37,117,39]`,
1989-01-01 through 1990-12-31. Actual authenticated server jobs and downloads,
using the Desktop client; not mocked and not a provider-driven model run.

**9/9 cases passed:** eight individual-variable requests and one combined request.
Combined job `77d384ed11674a58` returned 16 files, **4,710,385 bytes** total.

| Variable | Actual NetCDF units | Two-year download bytes |
| --- | --- | ---: |
| prec | kg m-2 s-1 | 532,852 |
| temp | K | 552,804 |
| srad | W m-2 | 460,191 |
| lrad | W m-2 | 369,313 |
| wind | m s-1 | 719,603 |
| pres | Pa | 527,054 |
| shum | kg kg-1 | 828,908 |
| rhum | % | 719,660 |

Each annual file was opened: 365 × 20 × 20 time/lat/lon, correct year and Jan–Dec
endpoints, daily spacing, coordinates inside the requested bbox, no masked or
nonfinite data, and units matching its manifest. Download sizes and SHA-256 were
verified. All **16 variable/year arrays** from combined delivery were numerically
identical to their corresponding individual-variable downloads.

A separate read-only request for `prec,not_a_real_cmfd_variable` returned HTTP 400
with `unknown_variable`, rather than silently dropping the invalid variable.

Important metadata discrepancy remains: catalogue describes precipitation as
`mm/day`, whereas actual files and the manifest use `kg m-2 s-1`. Preserve actual
units and apply any KI-required conversion explicitly, not from catalogue prose.

Limits: this confirms all eight listed variables for this specific daily product,
area and two years. It does not verify every year/region, 3-hourly products,
cell-wise fidelity against national originals, or complete VIC/CaMa preparation
and simulation. No scientific model was run. Both single and combined subsets
are retained (~9.42 MB total) for reproducibility.

Evidence: `output/cmfd-all-variables-2026-09-14/report.json`.
Reusable test: `scripts/test_cmfd_all_variables.py` (requires explicit permission
for live jobs/downloads); `--check-existing` compares already-downloaded files
without network requests.
