# s5 — Validation: `score_quincy_vs_fluxnet.py`

## Purpose
Compare the real-engine series with independent eddy-covariance fluxes and grade them with the
bands in `docs/validation_convention.yaml`.

## Inputs
`quincy_daily.csv`, FLUXNET2015 `FULLSET_DD.csv` of the same site.

## Outputs
`score.json` (daily and monthly NSE/KGE/PBIAS/RMSE/r per variable, annual sums),
`scored_pairs_daily.csv`, optional figure.

## Procedure
```
$PY tools/score_quincy_vs_fluxnet.py --daily_csv case/parsed/quincy_daily.csv --site FI-Hyy \
    --out_dir case/score --figure case/score/fluxnet_fit.png
```
Or the whole chain: `python KISSPATH_KI_ROOT/QUINCY/run_and_score.py <out_dir>`.

## Verification
- Obs columns: GPP_NT_VUT_REF, RECO_NT_VUT_REF, NEE_VUT_REF (g C m-2 day-1 in DD files), LE_F_MDS,
  H_F_MDS (W m-2); days with QC < 0.75 dropped; Feb 29 dropped.
- Headline: GPP daily r² ≥ 0.7 (validation_convention.yaml, Tramontana 2016 / Thum 2025).

## Traps
- FLUXNET DAILY carbon fluxes are g C m-2 day-1, not µmol m-2 s-1 (dt_quincy_033).
- Tower met drives the model, tower fluxes score it: the forcing is not independent of the site,
  but the scored fluxes are (tier "real").
- An equilibrium (spun-up) stand underestimates a managed forest's net sink (dt_quincy_044).

## Example
See SKILL.md §11 for the FI-Hyy 1996-2014 numbers.
