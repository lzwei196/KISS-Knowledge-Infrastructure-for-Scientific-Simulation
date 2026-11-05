# Stage 9 (real engine): parse output, check water balance, score against FLUXNET

**Purpose.** Turn engine `.out` tables into tidy CSV, check the water balance, compute metrics.

**Inputs.** `run/` dir; optional FLUXNET site dir (`FULLSET_MM.csv`), `forcing_meta.json`.

**Outputs.** `monthly_long.csv` (native unit, per-day unit, µmol m-2 s-1 for carbon),
`annual.csv` (EVERY annual table in the run dir, i.e. every `.out` without Jan..Dec columns,
and EVERY column of each, named `<table>_<column>`: per-PFT `cmass_BNE … cmass_Total`, `lai_*`,
`fpc_*`, `agpp_*`, `anpp_*`, `aaet_*`, `dens_*`, `cton_leaf_*`, `nmass_*`; `cflux_Veg/Repr/Soil/Fire/Est/NEE`;
`cpool_VegC/LitterC/SoilC/Total`; `tot_runoff_Surf/Drain/Base/Total`; `doc_Total`; nitrogen tables
`nflux_*`, `ngases_*`, `npool_*`, `nsources_*`, `soil_nflux_*`, `soil_npool_*`), `paired_monthly.csv`,
`summary.json` (`annual_tables`, `annual_tables_skipped` with reasons, `last_year_totals_by_cell`),
optional figure. Missing/unreadable FLUXNET file or bad scoring input -> exit 2.

**Cells.** Both CSVs keep every cell (Lon, Lat). Scoring against one tower and the water
balance use ONE cell: with more than one cell in the run pass `--cell LON LAT` (the tables'
2-decimal Lon/Lat); without it the tool stops (exit 2). Cells are never averaged. The water
balance also needs a one-line gridlist and reads P at that line's x/y indices.

**Procedure.**
```bash
python tools/parse_lpjguess_engine_output.py --run_dir run_detha/run --out_dir parsed \
  --fluxnet_dir KISSPATH_OBS/fluxnet/sites/DE-Tha \
  --forcing_meta forcing/forcing_meta.json --figure s8_validation.png --site DE-Tha
```
Units: monthly carbon kgC m-2 month-1 ×1000/days → gC m-2 d-1 (FLUXNET MM unit) ×0.9636 → µmol m-2 s-1.
ET = maet + mevap + mintercep vs LE_F_MDS × 0.0864/2.45. Months with NEE_VUT_REF_QC < 0.5 dropped.

**Verification.** `summary.json` water_balance residual_pct (DE-Tha: 0.4 %); metrics n_months.

**Traps.** dt_lpjguess_025 (GPP net of leaf respiration), 026 (maet = transpiration),
034 (NEE excludes fire; unmanaged spin-up, no stand history). Tables have 3 decimals (~0.03 gC m-2 d-1 resolution).

**Example (DE-Tha 1996-2014, 221 months, untuned).** GPP NSE 0.69, KGE 0.61, r 0.96, PBIAS −34.8 %;
RECO NSE 0.85; ET NSE 0.69, PBIAS +8.8 %; NEE NSE 0.01, r 0.83.
