# s2 — Site and parameters: `site_config.json` and `parameter_slm_run.list`

## Purpose
Set what makes the site (PFT, soil, location) and, optionally, change process parameters for
sensitivity or calibration.

## Inputs
- `build_quincy_site_config.py --lat --lon [--site ID | --pft NAME] --soil hwsd|explicit|default`
- `edit_quincy_parameters.py --set NAME=MULT [--pft N] --out p.list`

## Outputs
- `site_config.json`: `nml` = {group: {key: value}} written into qs.namelist, plus `provenance`.
- `parameter_slm_run.list`: namelist groups of multipliers.

## Procedure
```
$PY tools/build_quincy_site_config.py --lat 61.8474 --lon 24.2948 --site FI-Hyy --soil hwsd \
    --elevation_m 181 --out case/site_config.json
$PY tools/edit_quincy_parameters.py --list            # valid names per group (from engine source)
$PY tools/edit_quincy_parameters.py --set vcmax2n=1.1 --set sla=0.9 --pft 5 --out case/p.list
```
PFTs: 1 BEM, 2 BED, 3 BDR, 4 BDS, 5 NE (BNE), 6 NS, 7 TeH, 8 TrH, 9 TeP, 10 TrP, 11 TeC, 12 TrC, 13 BSO, 14 UAR.

## Verification
- `site_config.json` → `provenance.pft` names the engine csv row (FI-Hyy → BNE 5).
- After a run with `--param_list`, `run_manifest.json.parameters_applied` lists name, old, new;
  the engine file `parameter_sensi_param_values.txt` holds every parameter it read.

## Traps
- Texture as FRACTIONS (HWSD gives percent) and bulk density in kg m-3 (HWSD g cm-3) (dt_quincy_032).
- Texture must go into both `lnd_spq_nml` and `jsb_sse_nml`; the site tool does both (dt_quincy_032).
- HWSD at FI-Hyy is silty clay with 34 % organic C; the real site is a podzol on sandy till
  (dt_quincy_038). Use `--soil explicit` when site texture is known.
- Absolute parameter values are transformed by the engine before use (e.g. jmax2n/4); the tool
  always uses proportional mode (dt_quincy_036). PFT parameters exist for PFTs 1-8 only (dt_quincy_037).

## Example
`outputs/quincy_fihyy_real_engine/site_config.json`.
