# s10_calibration

## Purpose

Configure and parse HYPE's built-in calibration. This KI uses HYPE optimization modes such as MC, DEMC, SM, BN, and Q2 through `optpar.txt` and `info.txt` criteria settings; it does not require an external optimizer for the standard calibration path.

## Inputs

- `modelfiles/GeoClass.txt` from s2
- `info.txt` from s7
- Existing `modelfiles/par.txt`
- Optional `Qobs.txt` in `forcingdir/` for `rout` criteria
- Calibration method, criterion, computed variable, observed variable, and outlet SUBID
- HYPE calibration outputs in `resultdir/`

## Outputs

- `modelfiles/optpar.txt`
- Updated `info.txt` with `calibration Y` and `crit` lines
- HYPE calibration outputs such as `allsim.txt`, `bestsims.txt`, and `calibration.log`
- Optional `calibration_results.csv`, `best_par.txt`, `convergence.png`, and JSON summary

## Procedure

Set up Monte Carlo calibration:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s10_calibration/setup_calibration.py \
  --method MC \
  --geoclass outputs/hype_run/modelfiles/GeoClass.txt \
  --info_txt outputs/hype_run/info.txt \
  --output outputs/hype_run/modelfiles/optpar.txt \
  --num_runs 500 \
  --criterion MKG \
  --crit_variable cout \
  --obs_variable rout \
  --outlet_subid 3
```

Run HYPE with s7, then parse calibration results:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s10_calibration/parse_calibration_results.py \
  --result_dir outputs/hype_run/resultdir/ \
  --output_csv outputs/hype_run/calibration_results.csv \
  --output_par outputs/hype_run/best_par.txt \
  --geoclass outputs/hype_run/modelfiles/GeoClass.txt \
  --plot_convergence outputs/hype_run/convergence.png
```

For the pinned calibration runner used by this KI's `calibration.yaml` runner mode:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/calib_run.py \
  --workdir outputs/hype_run/ \
  --out outputs/hype_run/metrics.json
```

## Verification

- `optpar.txt` exists in `modelfiles/` and contains the exact 20 HYPE optimization info lines before parameter triplets, as implemented by `setup_calibration.py`.
- `info.txt` includes `calibration Y` and `crit` lines for the selected criterion and variables.
- `Qobs.txt` exists when `obs_variable rout` is used.
- After s7, `resultdir/allsim.txt` or `resultdir/bestsims.txt` exists before parsing.
- `parse_calibration_results.py` writes `best_par.txt` with parameter counts formatted from `GeoClass.txt`.

## Traps

- `dt_r02`: calibrated parameter files must still honor land-use and soil value counts from `GeoClass.txt`.
- `dt_r06`: calibration can stop early with `STOP 1`; check `hyss_*.log` in the info directory as well as `logdir/`.
- `dt_s02`: calibration may compensate for wrong discharge scale if `AREA` is in km2 instead of m2; fix `GeoData.txt` before calibrating.
- `dt_s05`: if `ForcKey.txt` and `GeoData.txt` SUBIDs do not match, calibration criteria can score a model with missing upstream forcing.

## Example

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s10_calibration/setup_calibration.py \
  --method DEMC \
  --geoclass outputs/hype_run/modelfiles/GeoClass.txt \
  --info_txt outputs/hype_run/info.txt \
  --output outputs/hype_run/modelfiles/optpar.txt \
  --demc_ngen 100 \
  --demc_npop 5 \
  --criterion MKG \
  --crit_variable cout \
  --obs_variable rout \
  --outlet_subid 3

python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s10_calibration/parse_calibration_results.py \
  --result_dir outputs/hype_run/resultdir/ \
  --output_csv outputs/hype_run/calibration_results.csv \
  --output_par outputs/hype_run/best_par.txt \
  --geoclass outputs/hype_run/modelfiles/GeoClass.txt \
  --plot_convergence outputs/hype_run/convergence.png
```
