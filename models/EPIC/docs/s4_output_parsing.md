# EPIC0810 Stage 4 — Output Parsing

## Purpose
Convert EPIC's whitespace-delimited Fortran output files into pandas DataFrames,
and scrape annual water-balance summaries from the human-readable `.OUT` report.

## Inputs
- Workspace path
- Site ID

## Outputs
- pandas DataFrames for `.ACY`, `.DGN`, `.ANN`, `.ACN`, `.DWT`
- dict of annual table rows from `.OUT` (e.g. `{"PRCP(mm)": [820, 845, ...]}`)

## Procedure
```python
from tools.parse_epic_output import (
    parse_acy, parse_dgn, parse_ann, water_balance_summary
)
import os
ws, sid = "/tmp/epic_run1", "umstead_0"
acy = parse_acy(os.path.join(ws, f"{sid}.ACY"))
dgn = parse_dgn(os.path.join(ws, f"{sid}.DGN"))
ann = parse_ann(os.path.join(ws, f"{sid}.ANN"))
wb = water_balance_summary(ws, sid)
print(wb)
```

All EPIC output files share a 10-line header (binary stamp, run header, file listing,
then a column-name line at row 11). The parser:
1. Reads all lines
2. Splits row 11 on whitespace → column names
3. Splits rows 12..N on whitespace, pads short rows to width
4. Attempts `pd.to_numeric` on each column

## Verification
For a successful run on the umstead test case (15 yr, 1930–1944):
- `parse_dgn` returns daily rows when `DGN` toggle is enabled in `PRNT1102.DAT`
- `parse_ann` returns annual rows
- `water_balance_summary` returns `PRCP(mm)`, `ET(mm)`, `Q(mm)` of length NBYR
- Mean annual precipitation matches the input `.DLY` totals (within rounding)

## Traps
- **Empty data tables** are normal when no harvest events occur (e.g. forest run
  produces zero `.ACY` rows). Use `.OUT` annual table instead via
  `parse_out_annual_table()`.
- **Stale headers** — the column-name row sometimes wraps across two lines for
  models with > 30 columns. The current parser handles only single-line headers;
  for `.DGN` and `.OUT` extended tables, treat the second header continuation as
  separate columns and rename manually.
- **Unit mismatch in OUT scrape** — labels like `WBMC(kg/ha)` carry units inline.
  Don't assume `(mm)` for everything.

## Example
```python
from tools.parse_epic_output import parse_dgn
df = parse_dgn("/tmp/epic_run1/umstead_0.DGN")
if not df.empty:
    print("ET range:", df["ET"].min(), df["ET"].max())
```
