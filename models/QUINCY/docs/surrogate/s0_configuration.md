# S0 Configuration

## Purpose

Define the single-site QUINCY run before any files are converted: site latitude and longitude, simulation period, forcing source, plant functional type (PFT), and output locations. In this KI, S0 has no standalone script; it is the configuration step described in `SKILL.md` and `dag.yaml` that feeds `tools/convert_forcing_to_quincy.py`, `tools/convert_parameters_to_quincy.py`, and `tools/run_quincy.py`.

## Inputs

- `SKILL.md`: authoritative stage table, input variable table, unit trap table, and notes.
- `dag.yaml`: model identity, scope, inputs, outputs, observability, and caveats for the analytic `QUINCYModel` implementation.
- `docs/format_spec.yaml`: projected input and output schema from the DAG and diagnostics.
- Site choices: `LAT`, `LON`, `START_YEAR`, `END_YEAR`, `PFT`, and forcing source (`fluxnet`, `cmfd`, `mswx`, or existing `quincy` CSV).

## Outputs

- A concrete run plan: source forcing path, output forcing CSV path, parameter JSON path, model output CSV path, parsed output CSV path, and summary JSON path.
- Shell variables or workflow parameters passed to S1-S4.

## Procedure

Inspect the KI stage definitions and input schema:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
sed -n '1,220p' SKILL.md
sed -n '1,180p' dag.yaml
sed -n '1,180p' docs/format_spec.yaml
```

Define a run configuration before invoking the tools:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
export LAT=61.85
export LON=24.29
export START_YEAR=2000
export END_YEAR=2005
export PFT=enf
export RUN_DIR=/tmp/quincy_fi_hyy
mkdir -p "$RUN_DIR"
```

Confirm the accepted PFT and source options from the tools:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/convert_forcing_to_quincy.py --help
python3 tools/convert_parameters_to_quincy.py --help
python3 tools/run_quincy.py --help
```

## Verification

- `LAT` is in `[-90, 90]`; `LON` is in `[-180, 360]`.
- For CMFD/MSWX, `START_YEAR` and `END_YEAR` are both set and `START_YEAR <= END_YEAR`; `tools/convert_forcing_to_quincy.py` enforces this in `validate_inputs`.
- `PFT` is one of the choices in `tools/convert_parameters_to_quincy.py`: `enf`, `dbf`, `ebf`, or `c3grass`.
- The selected source and target file paths are consistent with the remaining stage docs.

## Traps

- `dt_quincy_021`: wrong latitude hemisphere sign shifts the GPP seasonal cycle because daylength is derived from latitude.
- `dt_quincy_008`: using default boreal ENF parameters for a mismatched PFT can create a 2-3x GPP bias.
- `dt_quincy_015`: upstream QUINCY spin-up guidance does not apply cleanly to this analytic no-pool reimplementation; do not assume annual carbon closure from configuration alone.

## Example

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
export LAT=61.85 LON=24.29 START_YEAR=2000 END_YEAR=2005 PFT=enf
export RUN_DIR=/tmp/quincy_fi_hyy
mkdir -p "$RUN_DIR"
python3 tools/convert_parameters_to_quincy.py --operation defaults --pft "$PFT" --fout "$RUN_DIR/${PFT}_params.json"
```
