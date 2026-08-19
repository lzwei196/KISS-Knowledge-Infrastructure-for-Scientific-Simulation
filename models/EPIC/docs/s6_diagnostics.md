# EPIC0810 Stage 6 — Diagnostics & Recovery

## Purpose
When EPIC0810 crashes, hangs, or produces empty/wrong output, follow this protocol
*before* writing any debug script.

## Procedure
1. **Check `diagnostics/triplets.yaml`** for a matching error pattern. Common
   crashes are already documented there.
2. **Read the manual** — EPIC1102 user manual covers most file format questions
   (the format hasn't changed since 0810). Texas A&M AgriLife BREC site has the PDF.
3. **Inspect the bundled example** at
   `KISSPATH_BINARIES/EPIC/source/repo/epic1102_example_files_20221002/`
   — the `umstead.SOL`, `umstead.OPC`, `NCRDU.DLY` files are *known to work*
   (after sanitization). Diff your generated files against these.
4. **Fix the tool**, not the workspace by hand. The error you found should
   become a triplet entry.

## Common symptoms

| Symptom | Likely cause | Triplet ID |
|---------|--------------|------------|
| `forrtl: severe (29)` unit 39 fort.39 | Missing `SOIL38K.DAT` alias | T01 |
| `forrtl: severe (64)` input conversion error unit 24 | Alpha tokens in `.SOL` | T02 |
| Hangs at `FORTRAN PAUSE PAUSE prompt>` | stdin not closed | T03 |
| OUT file < 1 KB | EPICRUN.DAT line not terminated with `/` | T04 |
| Empty ACY/DGN | Output toggles disabled in `PRNT1102.DAT` | T05 |
| All zeros in ANN | Start year before .DLY range | T06 |
| Crash on year 1 day 1 | Tmax < Tmin in DLY | T07 |
| Yield always 0 | Wrong PHU in OPC planting row | T08 |
| ET > P | RH in percent not fraction | T09 |
| Negative LAI | Crop code missing from CROPCOM.DAT | T10 |

## Verification of a healthy run
```bash
ls -la /tmp/epic_run1/umstead_0.OUT     # > 10 KB
grep -c "EPIC0810" /tmp/epic_run1/umstead_0.OUT   # >= 1
grep -c "ANNUAL HEAT UNITS" /tmp/epic_run1/umstead_0.OUT  # >= 1
```

## Traps
- **Don't run the binary outside the workspace dir** — `EPICFILE.DAT` references
  list/database files relative to `cwd`. Always `subprocess.run(..., cwd=workspace)`.
- **Don't edit binary files** — every `.DAT` referenced by `EPICFILE.DAT` is a
  text file, but `SOIL35K.DAT` and `SOIL38K.DAT` look like binaries to `cat` and
  must be copied byte-for-byte.
- **Don't assume PRNT1102.DAT is human-readable** — the toggles are positional
  and version-specific. Modify only via `update_prnt_toggles()` if you write one;
  don't hand-edit.
