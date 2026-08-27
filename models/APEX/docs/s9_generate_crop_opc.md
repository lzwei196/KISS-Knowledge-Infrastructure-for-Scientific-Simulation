# S9 Generate Crop OPC

## Purpose

Generate an APEX0806-compatible crop operation schedule for a selected crop, latitude, and optional longitude, then wire the management list so APEX actually reads it. This is the normal stage for replacing the Riesel-TX template rotations with a target crop.

## Inputs

- A workspace from S1
- `tools/s9_generate_crop_opc.py`
- Crop name: `corn`, `wheat`, `spring_wheat`, `soybean`, `rice`, `cotton`, `sorghum`, or `pasture`
- Latitude, optional longitude
- Optional `--ggcmi-dir` for GGCMI Phase 3 planting/harvest dates
- Optional `--npkgrids-dir` or `--n-rate` for fertilizer rates
- `OPSCCOM.DAT`, `FERTCOM.DAT`, and `TILLCOM.DAT` from the workspace

## Outputs

- A generated `OPSC01.mgt` or user-specified output file
- APEX0806 operation codes: plant 136, fertilize 261, harvest 292, field cultivator 160, kill crop 451
- APEX0806 fertilizer codes: elemental N 53 and elemental P 54
- `OPSCCOM.DAT` rewritten by `wire_management_list()` when called through `tools/quickstart.py` or the Python API

## Procedure

```bash
cd KISSPATH_KI_ROOT/APEX/knowledge_infrastructure
python tools/s1_setup_workspace.py /tmp/apex_ws
python tools/s9_generate_crop_opc.py \
  --workspace /tmp/apex_ws \
  --crop corn \
  --lat 32.94 --lon 117.36 \
  --n-years 6 \
  --output /tmp/apex_ws/OPSC01.mgt
python - <<'PY'
from tools.s9_generate_crop_opc import wire_management_list
wire_management_list("/tmp/apex_ws", opc_name="OPSC01.MGT")
PY
```

The full `tools/quickstart.py` already calls `write_opc()` and then `wire_management_list()`.

## Verification

```bash
head -8 /tmp/apex_ws/OPSC01.mgt
awk 'NR>2 && NF {print NF}' /tmp/apex_ws/OPSC01.mgt | sort -nu
cat /tmp/apex_ws/OPSCCOM.DAT
grep -n " 92 \| 93 \| 151 " /tmp/apex_ws/OPSC01.mgt || true
```

Data rows should have the expected APEX0806 schedule shape, `OPSCCOM.DAT` should reference `OPSC01.MGT`, and the grep should find no APEX1501-only fertilizer or invalid tillage codes.

## Traps

- `diagnostics/triplets.yaml:fert_code_pause` - fertilizer codes 92/93 are APEX1501 codes and block APEX0806.
- `diagnostics/triplets.yaml:apex0806_opc_tillage_151_pause` - code 151 is absent from this APEX0806 `TILLCOM.DAT`; use 160.
- `diagnostics/triplets.yaml:apex0806_opc_missing_kill_op` - generated schedules add op 451 after harvest to prevent crop carryover.
- `diagnostics/triplets.yaml:apex0806_opcode_mismatch` - plant/fertilize/harvest/kill codes differ between APEX0806 and APEX1501.
- `diagnostics/triplets.yaml:apex0806_opc_generated_not_wired` - writing the schedule is not enough; wire `OPSCCOM.DAT`.

## Example

```bash
python tools/s9_generate_crop_opc.py --workspace /tmp/apex_bengbu --crop corn --lat 32.94 --lon 117.36 --n-years 6 --output /tmp/apex_bengbu/OPSC01.mgt
python -c 'from tools.s9_generate_crop_opc import wire_management_list; wire_management_list("/tmp/apex_bengbu", opc_name="OPSC01.MGT")'
```
