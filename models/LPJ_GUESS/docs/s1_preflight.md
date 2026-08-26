# Stage 1: Preflight

## Purpose

Verify that this LPJ-GUESS KI is runnable before preparing inputs or executing the analytic model. This stage is mandatory in `SKILL.md` and exercises the HydroCraft Python interpreter, the four files in `tools/`, `diagnostics/triplets.yaml`, and a minimal `tools/run_lpjguess.py` smoke run.

## Inputs

- `preflight_check.py`
- `tools/convert_forcing_to_lpjguess.py`
- `tools/convert_parameters_to_lpjguess.py`
- `tools/run_lpjguess.py`
- `tools/parse_output_lpjguess.py`
- `diagnostics/triplets.yaml`
- HydroCraft Python interpreter expected by `preflight_check.py`: `KISSPATH_PYTHON_ENV/bin/python`

## Outputs

- Terminal check lines marked `OK` or `FAIL`.
- A final `PREFLIGHT_REPORT=...` JSON object with check status, subject path, criticality, and suggested fixes.
- Exit code `0` when all critical checks pass; exit code `1` when a critical dependency or smoke run fails.

## Procedure

Run from the KI root:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 preflight_check.py
```

If a critical check fails, inspect the matching diagnostic corpus before editing tools:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 - <<'PY'
import yaml
from pathlib import Path
triplets = yaml.safe_load(Path("diagnostics/triplets.yaml").read_text())
for entry in triplets:
    if entry["id"] in {"dt_lpjguess_007", "dt_lpjguess_014"}:
        print(entry["id"], entry["symptom"]["description"])
PY
```

The preflight itself compiles each tool, starts `tools/run_lpjguess.py --help`, and writes temporary two-row forcing and parameter files for a smoke run.

## Verification

Confirm the output includes:

- `OK` for `data: .../tools`
- `OK` for `data: .../diagnostics/triplets.yaml`
- `OK` for `binary: KISSPATH_PYTHON_ENV/bin/python`
- `OK` for every file in `tools/`
- `OK` for `run: .../tools/run_lpjguess.py minimal smoke run`
- `PREFLIGHT_REPORT=` at the end

The smoke-run output must contain `date`, `GPP`, `Ra`, `Rh`, `Reco`, `NEE`, and `NPP`, matching the output contract in `docs/format_spec.yaml`.

## Traps

- `dt_lpjguess_007`: if preflight or a later run reports missing `SW_IN`, `TA`, or `VPD`, the forcing table is not in the format consumed by `tools/run_lpjguess.py`; regenerate it with `tools/convert_forcing_to_lpjguess.py`.
- `dt_lpjguess_014`: if the smoke output violates `NEE = Reco - GPP`, inspect `tools/run_lpjguess.py` rather than post-processing the error away.
- `dt_lpjguess_004`: this KI emits carbon fluxes in `umol CO2/m2/s`; do not compare preflight or model output to `gC/m2/day` observations without conversion.

## Example

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 preflight_check.py
```

Use the preflight report as the first failure artifact when opening a debugging session.
