# S6 Execution

## Purpose

Run the actual DLBreach Fortran binary on the assembled `casename.txt` file and produce `casename.out`. This stage must use `tools/s6_execution/run_dlbreach.py`, which automates the stdin case-name prompt, Wine/native execution, stale-output deletion, and peak-discharge parsing.

## Inputs

- `--casename`: case name without `.txt`.
- `--work_dir`: directory containing `casename.txt`.
- Optional `--dlbreach_path` if the binary is outside the default paths.
- Optional `--timeout`.

## Outputs

- `WORKDIR/CASE.out`, the raw DLBreach 13-column ASCII output.
- JSON metadata with `output_file`, `binary_path`, `exit_code`, `runtime_sec`, `peak_results`, stdout/stderr excerpts, and `status`.

## Procedure

After S5 has written `outputs/demo/demo.txt`, run:

```bash
python3 tools/s6_execution/run_dlbreach.py \
  --casename demo \
  --work_dir outputs/demo \
  --timeout 300 \
  --output outputs/demo/run.json
```

Use an explicit binary path only when auto-detection fails:

```bash
python3 tools/s6_execution/run_dlbreach.py \
  --casename demo \
  --work_dir outputs/demo \
  --dlbreach_path KISSPATH_BINARIES/dlbreach/bin/DLBreach_Barrier.exe \
  --output outputs/demo/run.json
```

The raw output columns are documented in `SKILL.md` and projected in `docs/format_spec.yaml`.

## Verification

- `status` is `success`.
- `output_file` points to a non-empty `.out` file.
- `peak_results.output_lines` is positive.
- The first numeric data row has 13 columns.

```bash
awk 'NF && $1 !~ /^[#!]/ {print NF; exit}' outputs/demo/demo.out
```

## Traps

- `dt_003`: `casename.txt` missing from `--work_dir`.
- `dt_004`: missing `Downstream_Channel_Flow_Out` can leave the output empty. Regenerate through S5.
- `dt_008`: `Simulation_Period` entered in hours instead of seconds yields only one or two output lines.
- `dt_019`: do not use `dlbreach.py`; it is not the validated Fortran executable and can underpredict peak discharge by about an order of magnitude.
- `dt_025`: explicit time step instability can produce NaN, Inf, oscillatory discharge, or crashes. Reduce `Time_Step` and compare a half-step rerun.
- `dt_027`: stale `.out` files can be parsed after manual runs. `run_dlbreach.py` deletes stale output before execution.

## Example

```bash
cd KISSPATH_KI_ROOT/DLBreach/knowledge_infrastructure
python3 tools/s6_execution/run_dlbreach.py \
  --casename example_case \
  --work_dir outputs/example_case \
  --timeout 600 \
  --output outputs/example_case/run.json
```

