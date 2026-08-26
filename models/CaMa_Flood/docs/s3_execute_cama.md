# Stage 3: Execute CaMa-Flood

## Purpose

Run the actual CaMa-Flood Fortran binary through the generated shell script, preserving the KI guardrail that forbids substituting a simplified routing implementation.

## Inputs

- `tools/run_cama.py`
- Generated run script, for example `KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh`
- Executable binary `KISSPATH_BINARIES/cmf_v420_pkg/src/MAIN_cmf`
- Basin map directory from Stage 2
- Yearly `Runoff` NetCDF forcing from Stage 1

## Outputs

- CaMa output NetCDF files in the script `RDIR`, for example:
  - `o_outflwYYYY.nc`
  - `o_rivdphYYYY.nc`
  - `o_sfcelvYYYY.nc`
  - `o_flddphYYYY.nc`
  - `o_fldfrcYYYY.nc`
- Restart files such as `restartYYYY010100.nc`
- Console diagnostics from `tools/run_cama.py`

## Procedure

Run the preflight-only execution check first:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/run_cama.py \
  --script KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh \
  --dry_run
```

Execute the model:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/run_cama.py \
  --script KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh \
  --timeout 7200
```

`tools/run_cama.py` runs `bash <script>` from the script directory, then verifies output files and performs a discharge sanity check when `outflw` exists.

## Verification

Check for expected output in the Bengbu validation output directory named in `SKILL.md`:

```bash
ls KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/o_outflw2003.nc
ls KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/o_flddph2003.nc
```

Inspect the generated namelist paths after a run:

```bash
grep -n "CDIMINFO\|CNEXTXY\|CINPMAT\|CROFCDF" KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama/input_cmf.nam
```

All file references should be absolute paths.

## Traps

- `dt_cama_001`: relative namelist paths cause `STOP 10` because the generated script changes into `RDIR` before `MAIN_cmf` opens files.
- `dt_002`: missing or non-executable `MAIN_cmf`. Rebuild or restore the binary before running.
- `dt_cama_009`: output discharge above plausible basin scale can indicate runoff was pre-converted to `m3/s`.
- `dt_016`: cold-start year used for scoring. The generated script supports spin-up; exclude the first simulated year from formal validation when needed.

## Example

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/run_cama.py \
  --script KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh \
  --timeout 7200
```

Successful runs report created `o_*.nc` files and the output directory.
