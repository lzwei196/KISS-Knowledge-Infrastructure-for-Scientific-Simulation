# s9: Control File Assembly — Skill Document

## Purpose

Assemble the CE-QUAL-W2 master control file `w2_con.npt` from all upstream tool outputs. This is the most error-prone stage because w2_con.npt uses **8-character fixed-width fields** read by Fortran column position. A single misalignment corrupts all downstream values silently.

## Prerequisites

- [ ] `reservoir_grid.json` from s1 (bathymetry dimensions)
- [ ] `met_wb1.npt` from s3 (meteorological forcing)
- [ ] `qin_br*.npt` from s4 (inflow discharge)
- [ ] `tin_br*.npt` from s4 (inflow temperature)
- [ ] `qot_br*.npt` from s5 (outflow discharge)
- [ ] `init_conditions.json` from s6
- [ ] `hydraulic_params.json` from s7
- [ ] `wq_config.json` from s8 (if WQ enabled)
- [ ] All input files copied/symlinked to the run directory

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Grid JSON | File | s1 | Segment/layer counts, bathymetry dimensions |
| Met file | File | s3 | Path to met_wb1.npt |
| Inflow files | Files | s4 | qin_br*.npt, tin_br*.npt paths |
| Outflow files | Files | s5 | qot_br*.npt path |
| Simulation year | Integer | s0 | YEAR parameter |
| Start/end JDAY | Float | s0 | TMSTRT and TMEND |

## Procedure

### Step 1: Gather all upstream outputs

Verify all required files exist:
```bash
test -f reservoir_grid.json && test -f met_wb1.npt && test -f qin_br1.npt && echo "All files present"
```

### Step 2: Run generate_w2_control

```bash
python tools/s9_control_file/generate_w2_control.py \
    --grid_json reservoir_grid.json \
    --met_file met_wb1.npt \
    --qin_files qin_br1.npt \
    --tin_files tin_br1.npt \
    --year 2005 \
    --start_jday 1.0 --end_jday 365.0 \
    --output w2_con.npt
```

### Step 3: Critical validation — 8-character field alignment (dt_006)

**This is the single most important validation step.**

Every numeric field in w2_con.npt must be exactly 8 characters, right-justified:
```
Good: "     1.0"  (8 chars: 5 spaces + "1.0")
Bad:  "    1.0"   (7 chars — everything after this shifts left)
Bad:  "      1.0" (9 chars — everything after this shifts right)
```

Verify with:
```bash
# Check that GRID line has correct field widths
head -10 w2_con.npt
# NWB, NBR, IMX, KMX should each be in 8-char fields
```

### Step 4: Cross-reference validation

1. **IMX matches bathymetry**: `python -c "import json; g=json.load(open('reservoir_grid.json')); print('IMX =', g['n_segments'])"`
2. **KMX matches bathymetry**: Same JSON, `n_layers` field
3. **Branch segments valid**: US, DS within [1, IMX]
4. **All file paths < 72 chars** (dt_008):
```bash
grep -E '\.(npt|csv|nc)' w2_con.npt | awk '{print length, $0}' | sort -rn | head -5
```
5. **TMSTRT/TMEND match forcing**: First/last JDAY in met_wb1.npt must cover TMSTRT-TMEND

### Step 5: Copy all files to run directory

CE-QUAL-W2 reads w2_con.npt from the current working directory. All referenced files must be in the same directory (or at the paths specified in w2_con.npt):

```bash
cp bth_wb1.npt met_wb1.npt qin_br1.npt tin_br1.npt qot_br1.npt w2_con.npt <run_dir>/
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| Control file | `w2_con.npt` | File exists, > 500 bytes, contains GRID, TIME, BRANCH cards |

## Validation Checks

1. File size > 500 bytes: `stat -c%s w2_con.npt`
2. Contains required cards: `grep -c "GRID\|TIME CON\|BRANCH\|MET FILE" w2_con.npt` >= 4
3. No path > 72 chars: `grep -oP '.{73,}' w2_con.npt | wc -l` should be 0
4. ELWS > all ELBOT values
5. Constituent count matches inflow file columns (if WQ enabled)

## Common Pitfalls

| Pitfall | Triplet | Prevention |
|---------|---------|-----------|
| 8-char column misalignment | dt_006 | Use `fmt_int(val, 8)` and `fmt_float(val, 8, 2)` |
| Path > 72 chars | dt_008 | Use `os.path.basename()` for all file references |
| Input file shorter than sim period | dt_009 | Validate JDAY range of all input files |
| Constituent flag mismatch | dt_015 | Count ON flags = count cin_br*.npt columns |
| ELWS < ELBOT at upstream | dt_014 | Set ELWS >= max(all bottom elevations) |

### w2_con.npt Card Group Reference

The control file has ~50 card groups. Each starts with an 8-char header. Critical groups:

| Card | Purpose | Key fields |
|------|---------|-----------|
| TITLE | 3 title lines | Free text |
| GRID | Grid dimensions | NWB, NBR, IMX, KMX |
| TIME CON | Simulation period | TMSTRT, TMEND, YEAR |
| DLT CON | Timestep control | NDT, DLTMIN |
| CALCU | What to compute | VEL, TEMP, CONSTI |
| BR GEOM | Branch geometry | US, DS, UHS, DHS, SLOPE |
| INIT CND | Initial conditions | T2I, ICE, ELBOT, ELWS |
| MET FILE | Met file path | METFN |
| HYD COEF | Hydraulic coeffs | AX, DX, CBHE, TSED |
| EX COEF | Light extinction | EXH2O, BETA |
| QIN FILE | Inflow file paths | QINFN |
| QOT FILE | Outflow file paths | QOTFN |
| BTH FILE | Bathymetry paths | BTHFN |
| CONSTITU | WQ on/off flags | CCC (per constituent) |
| SNP FREQ | Snapshot output | NSNP, SNPD |
| TSR FREQ | Time series output | NTSR, TSRD |
