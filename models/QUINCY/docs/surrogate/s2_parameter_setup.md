# S2 Parameter Setup

## Purpose

Create, validate, query, or modify the PFT parameter JSON used by the analytic QUINCY model. The tool is `tools/convert_parameters_to_quincy.py`, and its defaults encode this KI's coupled C-N-P parameter set for `enf`, `dbf`, `ebf`, and `c3grass`.

## Inputs

- `--operation defaults --pft <pft>` to create a default parameter file.
- `--fin <params.json>` for `validate`, `modify`, `query`, and `list`.
- `--param` and `--value` for single-parameter modification.
- Parameter ranges and PFT defaults defined in `tools/convert_parameters_to_quincy.py`.

## Outputs

- JSON parameter file with top-level metadata and `params`.
- Optional validation report JSON from `--report`.
- CLI JSON summaries for validation status and warnings.

## Procedure

Inspect available parameters and PFT defaults:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
sed -n '1,180p' tools/convert_parameters_to_quincy.py
python3 tools/convert_parameters_to_quincy.py --help
```

Create default ENF parameters:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/convert_parameters_to_quincy.py \
  --operation defaults \
  --pft enf \
  --fout /tmp/quincy_fi_hyy/enf_params.json
```

Validate and report the parameter file:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/convert_parameters_to_quincy.py \
  --operation validate \
  --fin /tmp/quincy_fi_hyy/enf_params.json \
  --report /tmp/quincy_fi_hyy/enf_params_report.json
```

Modify a parameter only when the change is ecologically justified:

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/convert_parameters_to_quincy.py \
  --operation modify \
  --fin /tmp/quincy_fi_hyy/enf_params.json \
  --param vcmax25 \
  --value 50.0 \
  --fout /tmp/quincy_fi_hyy/enf_params_vcmax50.json
```

## Verification

- `validate` returns no errors for all required keys.
- Values stay inside `PARAMETER_RANGES` in `tools/convert_parameters_to_quincy.py`.
- `lai_min < lai_max` for a meaningful seasonal LAI response.
- Activation energies are in `J/mol`, not `kJ/mol`.
- `n_leaf_ref` is in `gN/m2_leaf`; it controls `vcmax25_eff = vcmax_n_slope * n_leaf_ref`, capped at `vcmax25`.

## Traps

- `dt_quincy_004`: leaf nitrogen in kgN or mgN instead of gN shuts down N-limited GPP.
- `dt_quincy_007`: `lai_min == lai_max` removes the seasonal GPP cycle.
- `dt_quincy_008`: PFT-mismatched `vcmax25` creates large GPP magnitude bias.
- `dt_quincy_009`: high `rh_q10` or `rh_base` inflates Reco and NEE.
- `dt_quincy_016`: stoichiometry must use C:N and C:P ratios, not reciprocals.
- `dt_quincy_017`: parameter JSON must use the exact keys expected by the converter.
- `dt_quincy_018`: activation energies are J/mol.
- `dt_quincy_022`, `dt_quincy_023`, `dt_quincy_024`: LAI, growth respiration, and Rh moisture parameters have stage-specific failure modes.

## Example

```bash
cd KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
python3 tools/convert_parameters_to_quincy.py --operation defaults --pft enf --fout /tmp/quincy_fi_hyy/enf_params.json
python3 tools/convert_parameters_to_quincy.py --operation query --fin /tmp/quincy_fi_hyy/enf_params.json --param n_leaf_ref
python3 tools/convert_parameters_to_quincy.py --operation validate --fin /tmp/quincy_fi_hyy/enf_params.json
```
