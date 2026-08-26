# S1 Installation

## Purpose

Verify that this KI can run the mandated DLBreach 2016.4 Fortran executable, either as a native binary or as a Windows executable through Wine. This stage enforces the `SKILL.md` mandatory execution policy: do not substitute `dlbreach.py` or any simplified Python approximation.

## Inputs

- Optional binary path supplied with `--dlbreach_path`.
- Default binary locations searched by `tools/s1_installation/verify_dlbreach.py`.
- Runtime environment with Wine if the detected executable is `.exe`.

## Outputs

- JSON printed to stdout, or captured by the caller, with `binary_path`, `platform`, `wine_path`, `test_passed`, `test_message`, and `status`.
- Exit code 0 only when the binary is found and a minimal DLBreach run produces a non-empty 13-column output.

## Procedure

Run preflight from the KI root:

```bash
python3 preflight_check.py
```

Then run the installation verifier directly when you need structured details:

```bash
python3 tools/s1_installation/verify_dlbreach.py --json
```

If the binary is installed outside the default search paths:

```bash
python3 tools/s1_installation/verify_dlbreach.py \
  --dlbreach_path KISSPATH_BINARIES/dlbreach/bin/DLBreach_Barrier.exe \
  --json
```

For format and model constraints, read `SKILL.md`, `docs/format_spec.yaml`, and `docs/REFERENCES.md`.

## Verification

- `status` should be `success`.
- `test_passed` should be true.
- `test_message` should mention 13 columns.
- If the verifier fails, check `diagnostics/triplets.yaml` before changing tools or inputs.

## Traps

- `dt_001`: binary not found. Place `DLBreach_Barrier.exe` or `DLBreach.exe` under the model binary directory used by the tools.
- `dt_002`: Windows executable detected without Wine. Install Wine or provide a native executable.
- `dt_023`: preflight can report `test_failed` because the embedded minimal test lacks `Downstream_Channel_Flow_Out`; patch `MINIMAL_TEST_INPUT` in `tools/s1_installation/verify_dlbreach.py` if that exact symptom appears.

## Example

```bash
cd KISSPATH_KI_ROOT/DLBreach/knowledge_infrastructure
python3 tools/s1_installation/verify_dlbreach.py --json
```

