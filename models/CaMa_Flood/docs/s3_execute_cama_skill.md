# Stage 3: Execute CaMa-Flood Skill

Thin wrapper for the preserved detailed note: [s3_execute_cama.md](s3_execute_cama.md).

## Purpose

Run the actual CaMa-Flood Fortran executable through the generated shell script and produce yearly routing outputs. This stage enforces the KI guardrail in `SKILL.md`: no simplified Python routing substitute is scientifically valid.

## Inputs

- `tools/run_cama.py`
- Run script: `KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh`
- Binary: `KISSPATH_BINARIES/cmf_v420_pkg/src/MAIN_cmf`
- Stage 2 map directory: `KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min/`
- Stage 1 forcing directory: `KISSPATH_ROOT/ata-kdt/bengbu_ki_driven/outputs/cama_input`
- `diagnostics/triplets.yaml`

## Outputs

- Output NetCDFs in `KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/`
- Files such as `o_outflw2003.nc`, `o_rivdph2003.nc`, `o_sfcelv2003.nc`, `o_flddph2003.nc`, and `o_fldfrc2003.nc`
- Restart files such as `restartYYYY010100.nc`
- Execution diagnostics from `tools/run_cama.py`

## Procedure

Run a dry preflight against the generated script:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/run_cama.py \
  --script KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh \
  --dry_run
```

Then execute the model with an explicit timeout:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/run_cama.py \
  --script KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh \
  --timeout 7200
```

The wrapper runs `bash <script>` from the script directory, checks known error patterns, and verifies output files after a successful exit.

## Verification

Check the existing Bengbu validation products and inspect the namelist paths:

```bash
test -s KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/o_outflw2003.nc
test -s KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/o_flddph2003.nc
grep -n "CDIMINFO\|CNEXTXY\|CINPMAT\|CROFCDF" KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/input_cmf.nam
```

All `CDIMINFO`, `CNEXTXY`, `CINPMAT`, and `CROFCDF` paths should be absolute paths under the bound CaMa-Flood tree or the selected forcing directory.

## Traps

- `dt_001`: relative namelist paths trigger `STOP 10` or file-open failures because the generated script changes into `RDIR` before `MAIN_cmf` opens files.
- `dt_002`: `MAIN_cmf` is missing, not executable, or fails startup; repair the Fortran binary before running.
- `dt_004`: discharge above plausible basin scale can come from feeding `m3/s` values as `Runoff`.
- `dt_016`: cold-start storage contaminates the first simulated year; use spin-up restarts or exclude the cold-start year from scoring.

## Example

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/run_cama.py \
  --script KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh \
  --dry_run
```

