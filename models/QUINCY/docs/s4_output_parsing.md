# s4 — Output parsing: `parse_quincy_engine_output.py`

## Purpose
Turn the engine's interval-summed text tables into dated daily series in FLUXNET units, and run
the balance checks.

## Inputs
A successful run dir (`run_manifest.json` status ok, daily output).

## Outputs
`quincy_daily.csv` (date; GPP, NPP, Ra, Rh, Reco, NEE in µmol CO2 m-2 s-1 and *_gC in g C m-2 day-1;
LE, H, Rnet, G in W m-2; P, ET, T, Q in mm day-1; LAI; fPAR; root-zone soil moisture),
`quincy_spinup_yearly.csv`, `quincy_summary.json`.

## Procedure
```
$PY tools/parse_quincy_engine_output.py --run_dir case/run --out_dir case/parsed
```

## Engine units (mo_qs_output_txt.f90)
- C fluxes: sum over the interval of µmol m-2 s-1 × dtime / 1e6 → mol C m-2 day-1 (daily output).
- Energy: W m-2 × dtime / 1e6 → MJ m-2 day-1; `Qh`, `Qle` upward positive.
- Water: kg m-2 s-1 × dtime → mm per interval. `Evaporation` = bare-soil only.
- `Time` = day of the 365-day year (restarts every year).
Derived: Ra = GrowthResp + MaintResp + NTransformResp + NFixationResp; Reco = Ra + HetResp;
NEE = Reco − GPP (positive = source); ET = Evaporation + Transpiration + Interception.

## Verification
- Exit 3 when NaN appears, LE/(λ·ET) is outside 0.7-1.5, or P − ET − Q exceeds 50 % of P (a unit-size error). A residual above 10 % is only a warning: the balance has no storage term and ET lacks snow sublimation.
- `spinup_drift.EcoC_trend_pct_per_100yr` small (a few %) = near equilibrium.

## Traps
- Snow sublimation is in LE but not in the water files; LE/(λ·ET) ≈ 1.15-1.2 at boreal sites is
  expected (warning only) (dt_quincy_039).
- Monthly engine output = 30-day blocks, not calendar months; the parser accepts daily output only
  (dt_quincy_042).
- Dates: day i = i-th day from 1 Jan of the first forcing year, Feb 29 skipped (dt_quincy_028).

## Example
`outputs/quincy_fihyy_real_engine/parsed/quincy_summary.json`.
