# S8 Update Operations

## Purpose

Edit an existing APEX operation schedule in place when a full generated schedule is not needed. `tools/s8_update_operations.py` is mainly for targeted management-file repairs, especially replacing the plant ID in column 6 while preserving the rest of each row.

## Inputs

- A workspace from S1
- `tools/s8_update_operations.py`
- Existing `OPSC01.MGT` or another `*.MGT` / `*.OPC` file
- Old and new plant IDs from `CROPCOM.DAT` / `PLANTABLE.DAT`

## Outputs

- The selected operation schedule with matching column-6 plant IDs replaced
- Validation that each data row still has parseable operation columns

## Procedure

```bash
cd KISSPATH_KI_ROOT/APEX/knowledge_infrastructure
python tools/s8_update_operations.py replace-plant-code \
  --workspace /tmp/apex_ws \
  --old 187 \
  --new 2
```

For structural schedule changes, use the Python API `rewrite_from_rows()` with explicit `OperationRow` values; for crop calendar and fertilizer generation, use S9 instead.

## Verification

```bash
grep -n " 187 " /tmp/apex_ws/OPSC01.MGT || true
grep -n "   2 " /tmp/apex_ws/OPSC01.MGT | head
```

Also inspect row fields with `awk '{print NF}' /tmp/apex_ws/OPSC01.MGT | tail` before running S6.

## Traps

- `diagnostics/triplets.yaml:apex0806_opcode_mismatch` - APEX0806 operation codes differ from APEX1501; do not patch in 1501 codes.
- `diagnostics/triplets.yaml:apex0806_opc_generated_not_wired` - editing or generating `OPSC01.MGT` is not sufficient unless `OPSCCOM.DAT` points subareas at that file.
- `diagnostics/triplets.yaml:apex0806_opc_missing_kill_op` - harvest without a following kill operation can cause year-3-plus crop carryover failure.
- `SKILL.md` OPC note - the crop ID is column 6, not the tillage/equipment column.

## Example

```bash
python tools/s8_update_operations.py replace-plant-code --workspace /tmp/apex_bengbu --old 187 --new 2
sed -n '1,8p' /tmp/apex_bengbu/OPSC01.MGT
```
