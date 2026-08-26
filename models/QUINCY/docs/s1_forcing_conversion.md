# S1 Forcing Conversion

## Purpose

Convert meteorological forcing into the QUINCY-format CSV consumed by `tools/run_quincy.py`. This KI supports FLUXNET2015 FULLSET CSV directly and contains placeholder CMFD/MSWX NetCDF readers that document the required unit conversions.

## Inputs

- Source forcing file or directory passed to `tools/convert_forcing_to_quincy.py --input`.
- `--source fluxnet`, `--source cmfd`, `--source mswx`, or `--source quincy`.
- `--lat` for daylength; `--lon` is accepted for site metadata.
- `--start-year` and `--end-year` for CMFD/MSWX.
- Expected FLUXNET columns are mapped in `tools/convert_forcing_to_quincy.py`: `SW_IN_F`, `TA_F`, `VPD_F`, `P_F`, `CO2_F_MDS`, plus optional observation columns.

## Outputs

- QUINCY forcing CSV with header and units row:
  `TIMESTAMP,YEAR,MONTH,SW_IN,TA,VPD,PRECIP,CO2,DAYLENGTH`.
- Optional observation columns when present and non-empty: `GPP_OBS`, `NEE_OBS`, `RECO_OBS`, `LE_OBS`, `H_OBS`.

## Procedure

Review converter source and accepted CLI flags:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
sed -n '1,120p' tools/convert_forcing_to_quincy.py
python3 tools/convert_forcing_to_quincy.py --help
```

Convert FLUXNET2015 monthly or daily data:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/convert_forcing_to_quincy.py \
  --source fluxnet \
  --input /path/to/FLX_FI-Hyy_FLUXNET2015_FULLSET_MM.csv \
  --output /tmp/quincy_fi_hyy/quincy_forcing.csv \
  --lat 61.85 \
  --lon 24.29 \
  --temporal auto
```

Validate an existing QUINCY forcing CSV before running the model:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/convert_forcing_to_quincy.py \
  --source quincy \
  --input /tmp/quincy_fi_hyy/quincy_forcing.csv \
  --operation validate
```

## Verification

- The converter prints a JSON result whose `status` is `success` or `completed_with_warnings`.
- Re-run `--operation validate` on the output forcing CSV.
- Inspect that monthly values fall inside the physical ranges encoded in `QUINCY_VARIABLES`: `TA` roughly `-60..55 degC`, `VPD` `0..80 hPa`, `PRECIP` `0..200 mm/day`, `CO2` `250..600 ppm`.
- Confirm the output includes `DAYLENGTH`; S3 scales GPP by `DAYLENGTH / 24`.

## Traps

- `dt_quincy_001`: CMFD/MSWX temperature left in Kelvin explodes Arrhenius rates.
- `dt_quincy_002`: CMFD precipitation left as `kg/m2/s` suppresses heterotrophic respiration.
- `dt_quincy_003`: VPD supplied as Pa or kPa instead of hPa distorts the Ci/Ca surrogate.
- `dt_quincy_005`: non-FULLSET FLUXNET column names can trigger missing-column failures.
- `dt_quincy_006`: FLUXNET `-9999` missing values must be converted to NaN.
- `dt_quincy_020`: CO2 must be ppm, not mole fraction.

## Example

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/convert_forcing_to_quincy.py \
  --source fluxnet \
  --input /data/fluxnet/FI-Hyy_FULLSET_MM.csv \
  --output /tmp/quincy_fi_hyy/quincy_forcing.csv \
  --lat 61.85 \
  --lon 24.29
python3 tools/convert_forcing_to_quincy.py \
  --source quincy \
  --input /tmp/quincy_fi_hyy/quincy_forcing.csv \
  --operation validate
```
