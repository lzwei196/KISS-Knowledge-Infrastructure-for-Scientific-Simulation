# Stage 06 — Output parsing and validation

## Purpose
Convert EPIC text output to CSV and run the water balance sanity check.

## Inputs
- Run name (e.g. `raleigh` → looks for `raleigh_0.ANN`, `raleigh_0.ACY`)
- Workspace containing the outputs

## Outputs
- `<run>_annual.csv` — P, ET, Q, PET, IRGA, DN, DN2O
- `<run>_yield.csv` — YLDG, BIOM, YLN, YLP, HI
- Console water balance report

## Procedure
1. Locate `<run>_0.ANN`. Skip header block (engine echo + variable names).
2. Header row starts with `YR` or `RUN`; data rows start with integer year.
3. Extract PRCP, ET, Q, PET, IRGA, DN, DN2O by column name.
4. Compute `residual = (P + IRGA) - (ET + Q)`.
5. Parse `<run>_0.ACY` similarly — keep all columns, dump to CSV.

## Verification
- CSV row count equals NBYR (minus spinup).
- Mean P in CSV matches mean of `.DLY` precip.
- After 2-yr spinup discard, |residual| < 50 mm/yr.

## Traps
- **Header markers**: EPIC prints either `RUN YR ...` or just `YR ...`.
  Parser handles both.
- **Spinup**: always discard first 2 years.
- **Irrigation budget**: include IRGA on input side of the balance.

## Example
```bash
python tools/parse_outputs.py --workspace /tmp/epic_output --name raleigh
```
