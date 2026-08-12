# Stage 04 — Operations schedule (.OPC)

## Purpose
Define the farm management calendar: plant, fertilize, irrigate, harvest,
kill, tillage. These operations drive plant growth, nutrient dynamics,
and residue management.

## Inputs
- Crop name (e.g. CORN, SOYB, WWHT) looked up in CROPCOM.DAT
- Plant date (MM-DD)
- Harvest date (MM-DD)
- Kill date (MM-DD)
- Fertilizer date + N rate (kg N/ha)
- Optional: multi-year rotation (multiple op blocks)

## Outputs
`<workspace>/<run>.OPC`, with:
- Line 0: free-form rotation title
- Line 1: rotation length + plant pop (from template)
- Lines 2+: op lines

Op line fixed layout:
```
YR MO DY  JD EQIP TRAC APPC  RATE  DEPTH  RATE2  MISC1..6
```

## Procedure
1. `select_crop.py --name CORN` → code.
2. Parse MM-DD strings → (month, day).
3. Julian day from `datetime.date(2001, mo, dy).timetuple().tm_yday`.
4. Emit ops in chronological order:
   - Plant (equip 136 = no-till drill)
   - Fert (equip 261 = anhydrous ammonia, fert# 87)
   - Harvest (equip 292)
   - Kill (equip 451)
5. Format each column with F8.2. Write with CRLF.

## Verification
- `.ACY` has one row per year × crop with `CPNM == <crop name>` and
  `YLDG > 0`.
- `.OUT` echoes each op with its Julian day.

## Traps
- **JD mismatch**: changing MM/DD but not JD → wrong day (EPIC_009).
  Tool computes JD automatically.
- **Wrong equipment code**: 292 on plant row = no seeding (EPIC_007).
- **Crop not in CROPCOM**: EPIC ships ~150 crops; custom crops require
  editing CROPCOM.DAT directly.

## Example
```bash
python tools/build_opc_file.py --name raleigh --crop CORN \
    --plant 04-24 --harvest 09-01 --kill 09-01 \
    --fert-day 04-24 --fert-n 143 --workspace /tmp/epic_run
```
