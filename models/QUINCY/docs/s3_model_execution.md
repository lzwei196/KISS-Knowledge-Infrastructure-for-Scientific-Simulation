# S3 Model Execution

## Purpose

Run this KI's analytic QUINCY reimplementation (`QUINCYModel` in `tools/run_quincy.py`) using a QUINCY-format forcing CSV from S1 and either a parameter JSON from S2 or built-in PFT defaults.

## Inputs

- `--forcing`: QUINCY forcing CSV with `SW_IN`, `TA`, `VPD`, `PRECIP`, `CO2`, and `DAYLENGTH`.
- `--params`: parameter JSON created by S2, or `--pft enf|dbf|ebf|c3grass` for defaults.
- `--lat`: optional latitude validation; daylength is already in the forcing CSV.
- `--calibrate`: optional SciPy-based calibration path in `tools/run_quincy.py`.

## Outputs

- Model output CSV with `TIMESTAMP`, model variables, and units row.
- Core variables: `GPP`, `NEE`, `RECO`, `RA`, `RH`, `LAI`, `LE`, `H`.
- Optional carried observation columns when they were present in the forcing CSV.

## Procedure

Inspect the execution wrapper and validation checks:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
sed -n '1,180p' tools/run_quincy.py
sed -n '385,490p' tools/run_quincy.py
python3 tools/run_quincy.py --help
```

Run with an explicit parameter file:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/run_quincy.py \
  --forcing /tmp/quincy_fi_hyy/quincy_forcing.csv \
  --params /tmp/quincy_fi_hyy/enf_params.json \
  --output /tmp/quincy_fi_hyy/quincy_output.csv \
  --lat 61.85
```

Run with PFT defaults instead of a parameter JSON:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/run_quincy.py \
  --forcing /tmp/quincy_fi_hyy/quincy_forcing.csv \
  --pft enf \
  --output /tmp/quincy_fi_hyy/quincy_output.csv \
  --lat 61.85
```

## Verification

- The JSON result prints `status: success` or `completed_with_warnings`; `status: error` exits nonzero.
- `tools/run_quincy.py` validates required forcing columns: `SW_IN`, `TA`, `VPD`, and `PRECIP`.
- Output warnings identify out-of-range `GPP`, `NEE`, `RECO`, or `LAI`.
- Inspect the CSV header and units row before parsing:

```bash
head -n 5 /tmp/quincy_fi_hyy/quincy_output.csv
```

## Traps

- `dt_quincy_011`: bad temperature forcing can produce NaN output through Arrhenius overflow.
- `dt_quincy_012`: NEE sign is `Reco - GPP`, positive means net source to atmosphere.
- `dt_quincy_013`: LE can exceed physical ranges if stomatal/water-use assumptions are wrong.
- `dt_quincy_014`: GPP must remain daylength-scaled by `DAYLENGTH / 24`.
- `dt_quincy_019`: missing Python dependencies such as NumPy/SciPy prevent runtime or calibration.

## Example

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/run_quincy.py \
  --forcing /tmp/quincy_fi_hyy/quincy_forcing.csv \
  --params /tmp/quincy_fi_hyy/enf_params.json \
  --output /tmp/quincy_fi_hyy/quincy_output.csv \
  --lat 61.85
head -n 5 /tmp/quincy_fi_hyy/quincy_output.csv
```
