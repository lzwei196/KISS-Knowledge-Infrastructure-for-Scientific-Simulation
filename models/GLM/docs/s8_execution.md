# s8 Execution

## Purpose

Run the actual GLM v3.3.3 binary through the KI wrapper, with preflight path checks and output validation. This KI must never substitute a simplified Python model for GLM.

## Inputs

- Run directory containing `glm3.nml`, `bcs/` forcing files, and optional `aed2.nml`.
- GLM binary, default `KISSPATH_BINARIES/glm/bin/glm`.
- Tool: `tools/s8_execution/run_glm.py`.

## Outputs

- `output/output.nc`
- `output/lake.csv`
- Optional `output/overflow.csv` and outlet/WQ CSV outputs configured in `glm3.nml`.
- JSON run summary with status, return code, elapsed time, output file sizes, and last stdout/stderr lines.

## Procedure

1. Run the KI preflight:

```bash
python preflight_check.py
```

2. Execute GLM from the run directory:

```bash
python tools/s8_execution/run_glm.py \
  --run_dir . \
  --nml_file glm3.nml \
  --timeout 3600
```

3. Use an explicit binary only when testing another installed GLM executable:

```bash
python tools/s8_execution/run_glm.py \
  --run_dir . \
  --glm_binary KISSPATH_BINARIES/glm/bin/glm \
  --nml_file glm3.nml \
  --timeout 3600
```

## Verification

- Wrapper JSON status is `success` or an understood `completed_with_warnings`.
- Stdout contains `Model Run Complete`.
- `output/output.nc` and `output/lake.csv` exist and are non-empty.
- For AED2 runs, WQ variables are finite and not all fill values before analysis.
- If execution fails, consult `diagnostics/triplets.yaml` before editing tools.

## Traps

- `dt_011`: GLM resolves `meteo_fl` relative to the current working directory.
- `dt_012`: inflow file paths must exist relative to `--run_dir`.
- `dt_013`: extreme forcing values can produce NaN temperatures during the run.
- `dt_014`: tropical/warm-climate ice growth usually means temperature or snow/ice settings are wrong.
- `dt_015`: too-small `max_layer_thick` can cause layer merge errors or apparent hangs.
- `dt_023` and `dt_027`: ice can be silently disabled without required snow/ice parameters.
- `dt_032`: GLM may exit 0 while AED2 WQ fields are NaN/fill.

## Example

```bash
python tools/s8_execution/run_glm.py \
  --run_dir . \
  --timeout 600
```
