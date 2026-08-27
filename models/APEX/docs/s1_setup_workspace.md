# S1 Setup Workspace

## Purpose

Create a fresh APEX0806 run workspace by copying the validated `examples/ex1_RiselTX/` template and placing `reference/APEX0806.exe` inside it. This stage enforces the KI rule from `SKILL.md`: copy the fixed-format APEX files first, then let later stages edit specific fields in place.

## Inputs

- `tools/s1_setup_workspace.py`
- `examples/ex1_RiselTX/`
- `reference/APEX0806.exe`
- Target workspace path, for example `/tmp/apex_ws`

## Outputs

- A populated workspace directory containing `APEXFILE.DAT`, `APEXRUN.DAT`, `APEXCONT.DAT`, `SITECOM.DAT`, `SOILCOM.DAT`, `OPSCCOM.DAT`, `CROPCOM.DAT`, `TILLCOM.DAT`, `FERTCOM.DAT`, `TR55COM.DAT`, and `APEX0806.exe`.
- Stale template outputs such as `*.OUT`, `*.ACY`, `*.DWS`, `*.RCH`, `RUN1501.SUM`, `fort.*`, and `EPICERR.DAT` are removed by `purge_template_outputs()`.

## Procedure

```bash
cd KISSPATH_KI_ROOT/APEX/knowledge_infrastructure
python preflight_check.py
python tools/s1_setup_workspace.py /tmp/apex_ws
```

The Python API is also available:

```python
from tools.s1_setup_workspace import setup
setup("/tmp/apex_ws")
```

## Verification

```bash
test -f /tmp/apex_ws/APEXFILE.DAT
test -f /tmp/apex_ws/APEX0806.exe
find /tmp/apex_ws -maxdepth 1 \( -name "*.ACY" -o -name "*.OUT" -o -name "fort.*" \) -print
```

The final `find` should print nothing on a fresh workspace. `tools/s1_setup_workspace.py` also calls `validate_outputs()` and fails if required template/control files are missing.

## Traps

- `diagnostics/triplets.yaml:file_missing_uppercase` - APEX file references are case-sensitive on Linux. Keep the filenames copied from `examples/ex1_RiselTX/` and do not casually lowercase extensions.
- `diagnostics/triplets.yaml:apex0806_template_outputs_parsed_as_results` - copied template run products can make `s7_parse_output.py` report plausible Texas results even if the new run never executed. S1 purges those files; recheck if a workspace was created by hand.
- `diagnostics/triplets.yaml:lwe_dat_missing` - workspaces not copied from this template can lack the `FLWE LWE.DAT` line and fail at unit 22.

## Example

```bash
python tools/s1_setup_workspace.py /tmp/apex_bengbu
ls /tmp/apex_bengbu/APEX0806.exe /tmp/apex_bengbu/APEXCONT.DAT
```
