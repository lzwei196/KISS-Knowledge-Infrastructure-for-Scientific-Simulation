# Stage 4: Run LPJ-GUESS Analytic Model

## Purpose

Execute this KI's Python analytic reimplementation of LPJ-GUESS core carbon flux physics. The runner loads converted forcing and parameter JSON, computes LUE GPP, Q10 autotrophic respiration, Q10 heterotrophic respiration, `Reco`, `NEE`, and `NPP`, and writes a raw model output CSV.

## Inputs

- `tools/run_lpjguess.py`
- Forcing CSV from `docs/s2_convert_forcing.md`
- Parameter JSON from `docs/s3_convert_parameters.md`
- Optional observation columns or file for calibration:
  - `--obs-file`
  - `--obs-gpp`
  - `--obs-nee`
  - `--calibrate`
  - `--cal-fraction`

## Outputs

A raw model CSV with:

- optional date columns copied from forcing: `date`, `year`, `month`
- forcing columns: `SW_IN`, `TA`, `VPD`
- model columns: `GPP`, `Ra`, `Rh`, `Reco`, `NEE`, `NPP`
- optional observation columns: `obs_GPP`, `obs_NEE`

All model fluxes are in `umol CO2/m2/s`.

## Procedure

Check the runner interface:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/run_lpjguess.py --help
```

Run the model using outputs from stages 2 and 3:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/run_lpjguess.py \
  --forcing /tmp/lpjguess_forcing.csv \
  --params /tmp/lpjguess_params.json \
  --output /tmp/lpjguess_model_output.csv
```

Run with calibration when the forcing or observation file has valid FLUXNET-style observation columns:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/run_lpjguess.py \
  --forcing /tmp/lpjguess_forcing.csv \
  --params /tmp/lpjguess_params.json \
  --output /tmp/lpjguess_model_output.csv \
  --obs-gpp GPP_NT_VUT_MEAN \
  --obs-nee NEE_VUT_MEAN \
  --calibrate \
  --cal-fraction 0.7
```

The model class and equations are in `tools/run_lpjguess.py`; the process boundaries are summarized in `dag.yaml`.

## Verification

Check row count and carbon identities:

```bash
python3 - <<'PY'
import pandas as pd
df = pd.read_csv("/tmp/lpjguess_model_output.csv")
print(df.columns.tolist())
print(df[["GPP", "Ra", "Rh", "Reco", "NEE", "NPP"]].describe())
print("max Reco-(Ra+Rh)", (df["Reco"] - (df["Ra"] + df["Rh"])).abs().max())
print("max NEE-(Reco-GPP)", (df["NEE"] - (df["Reco"] - df["GPP"])).abs().max())
PY
```

Expected checks:

- `GPP` is non-negative.
- `Ra`, `Rh`, and `Reco` are non-negative.
- `Reco = Ra + Rh` within floating-point tolerance.
- `NEE = Reco - GPP` within floating-point tolerance.
- The runner prints a JSON `Result` with `status` equal to `success` or `warning`.

## Traps

- `dt_lpjguess_014`: `NEE` must be `Reco - GPP`; if this identity fails, inspect `tools/run_lpjguess.py` before trusting parsed outputs.
- `dt_lpjguess_004`: the runner already converts internal GPP from `gC/m2/day` to `umol CO2/m2/s`; avoid converting the output a second time.
- `dt_lpjguess_011`: high GPP with otherwise plausible forcing usually points back to `LUE_max` in the stage 3 JSON.
- `dt_lpjguess_013`: high or low `Rh` usually points to `Rh_base`, `Rh_Q10`, `Rh_Tref`, or `C_pool_scale`.

## Example

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/run_lpjguess.py \
  --forcing /tmp/us_ha1_forcing_lpjguess.csv \
  --params /tmp/enf_lpjguess_params.json \
  --output /tmp/us_ha1_lpjguess_raw.csv
```

Use `/tmp/us_ha1_lpjguess_raw.csv` as the stage 5 `--input` file.
