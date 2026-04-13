# Stage 7: Output Parsing

## Purpose

Extract simulation results from GIFMod's raw columnar text output into clean CSV
files suitable for analysis, visualization, and comparison with observations.

## Inputs

| Input              | Source       | Format               | Required |
|--------------------|--------------|----------------------|----------|
| GIFMod output file | Model run    | Text (whitespace/tab)| Yes      |
| Variable selection | User         | List of names        | No       |
| Time range         | User         | Start/end days       | No       |
| Reference date     | User         | YYYY-MM-DD           | No       |

## Outputs

| Output             | Format | Description                        |
|--------------------|--------|------------------------------------|
| Results CSV        | CSV    | Clean time series with headers     |
| Summary statistics | JSON   | Min/max/mean for each variable     |

## Procedure

1. **Detect output format**: GIFMod output is whitespace or tab-delimited with a
   header row. The parser auto-detects the delimiter and column names.

2. **Read header**: Extract column names (e.g., `Time`, `Block1_Head`,
   `Block1_Conc`, `Block2_Flow`).

3. **Parse data rows**: Convert each line to floating-point values. Handle:
   - Whitespace-delimited columns
   - Tab-delimited columns
   - Comment lines (starting with `#`)
   - Empty lines

4. **Apply filters** (optional):
   - Variable filter: keep only selected columns
   - Time range: include only rows within [start_day, end_day]

5. **Add datetime column** (optional): Convert fractional days to ISO datetime
   using a reference start date.

6. **Compute statistics**: For each output variable, calculate min, max, mean,
   and count of valid values.

7. **Write CSV**: Output clean CSV with header row and consistent formatting.

## Verification

- [ ] Output CSV has header row with column names
- [ ] Time column is monotonically increasing
- [ ] No NaN values in critical columns (Head, Flow)
- [ ] Statistics are within physically reasonable ranges
- [ ] Row count matches expected time range

## Traps

| Trap                              | Consequence                      | Prevention              |
|-----------------------------------|----------------------------------|-------------------------|
| Mixed delimiters in output        | Misaligned columns               | Auto-detect delimiter   |
| Extremely large output files      | Memory issues during parsing     | Use line-by-line reader |
| Non-numeric values (overflow)     | Parse errors                     | Skip and warn           |
| Missing Time column               | Cannot align with observations   | Require Time as col 0   |
| Mass balance errors in output     | Unreliable results               | Check MB column if present|

## Example

```bash
# Parse all variables
python parse_gifmod_output.py \
  --input model_run/output.txt \
  --output results.csv

# Parse only Head and Flow, with date conversion
python parse_gifmod_output.py \
  --input model_run/output.txt \
  --output results_filtered.csv \
  --variables Head,Flow \
  --ref-date 2020-01-01 \
  --start-day 30 \
  --end-day 365
```

### Output CSV example:
```csv
datetime,Time_days,Soil_Head,Pond_Head,Pipe_Flow
2020-01-01 00:00:00,0.000000,1.200,0.500,0.012
2020-01-01 01:00:00,0.041667,1.205,0.505,0.013
```

### Summary statistics example:
```json
{
  "Soil_Head": {"min": 0.8, "max": 1.5, "mean": 1.15, "n": 8760},
  "Pipe_Flow": {"min": 0.0, "max": 2.5, "mean": 0.35, "n": 8760}
}
```

## Key Variables to Extract

| Variable Type   | Column Pattern    | Typical Range      | Unit     |
|-----------------|-------------------|--------------------|----------|
| Head            | *_Head, *_h       | 0 - 10 m           | m        |
| Flow            | *_Flow, *_Q       | 0 - 100 m^3/day    | m^3/day  |
| Concentration   | *_Conc, *_C       | 0 - 1000 mg/L      | user     |
| Moisture        | *_theta           | 0.05 - 0.50        | fraction |
| Mass Balance    | *_MB              | ~0 (should be < 1e-4)| user  |
| Storage         | *_S, *_Storage    | 0 - 1000 m^3       | m^3      |
