# Stage S5 — Extraction and analysis (DDlist100 + parser)

## Purpose
DayCent's primary output is a binary `.bin` file. Human-readable variables are
extracted by running `DDlist100_rev491` against the binary plus a variable list.
This stage turns the binary into a tidy CSV suitable for plotting and metric
computation.

## Inputs
- `<root>.bin` (from S4)
- `<varlist>.txt` — one variable per line; the canonical names are documented
  in the DayCent manual section "List of Output Variables"
- (optional) Observed CSV with `time,value` columns for metric computation

## Outputs
- `<prefix>.lis` — text table with header
- `<prefix>_tidy.csv` — clean CSV (from the parser)
- `metrics.json` — Pearson r, RMSE, NSE, bias against observed (if provided)

## Procedure
```bash
# 1. Extract from binary
./DDlist100_rev491 cb_nt wooster few_outvars.txt
# -> wooster.lis with the variables listed in few_outvars.txt

# 2. Parse to tidy CSV
python tools/parse_daycent_output.py \
    --lis wooster.lis --out wooster_tidy.csv

# 3. Compute metrics against observed
python tools/parse_daycent_output.py \
    --lis wooster.lis --var somsc \
    --observed wooster_obs_soc.csv \
    --metrics-out wooster_metrics.json
```

## Common variables

| Var | Unit | Description |
|-----|------|-------------|
| `time` | year (decimal) | DayCent decimal year |
| `aglivc` | g C/m² | Above-ground live carbon |
| `bglivcj` | g C/m² | Juvenile below-ground live C |
| `bglivcm` | g C/m² | Mature below-ground live C |
| `agcprd` | g C/m²/yr | Above-ground production |
| `bgcjprd` | g C/m²/yr | Juvenile BG production |
| `bgcmprd` | g C/m²/yr | Mature BG production |
| `cgrain` | g C/m² | Grain C at harvest |
| `accrst` | g C/m² | Accumulated crop residue |
| `cinput` | g C/m²/yr | Total C input to soil |
| `somsc` | g C/m² | **Total soil organic matter C** (the headline number) |
| `fertot11` | g N/m²/yr | Total fertiliser N applied |
| `omadtot` | g/m²/yr | Total organic amendment dry mass |
| `volpac` | g N/m²/yr | Volatilised ammonia N |
| `strmac2` | g N/m²/yr | NO3 leached from layer 2 |

The `few_outvars.txt` shipped with the Wooster example contains 13 of these.

## Verification
- The `.lis` file has at least one data row.
- Header line 2 contains the variable names you requested.
- `parse_daycent_output.py` reports `parsed: N rows x M cols` with M matching
  `wc -l varlist.txt`.

## Traps
- **Variable name typos:** DDlist100 silently ignores unknown variable names.
  Compare your varlist against the DayCent manual.
- **Multiple .bin files:** if you have `eq.bin`, `base.bin`, `cb_nt.bin`,
  passing `cb_nt` as the bin root extracts ONLY the treatment period. To get
  the full historical sweep, extract `base` instead, then concatenate.
- **Three-line vs four-line header:** older DayCent revisions wrote a 3-line
  header, rev 491 writes 2-line. The parser accepts both by trying to parse
  each line as floats.
- **Time column:** `time` is decimal year (e.g. 1962.5 for mid-1962). Match
  observations by rounding to nearest year, not by string equality.

## Example metric output
```json
{
  "variable": "somsc",
  "n": 4,
  "pearson_r": 0.41,
  "rmse": 1850.0,
  "bias": -1200.0,
  "nse": -2.1
}
```
