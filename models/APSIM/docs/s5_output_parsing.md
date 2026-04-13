# S5 — Output Parsing

## Purpose

Extract simulation results from APSIM's SQLite output database into
analysis-ready CSV format, with optional unit conversions for biomass
variables (g/m² → kg/ha → t/ha).

## Inputs

| Input                | Format     | Source              |
|----------------------|-----------|---------------------|
| Output database      | .db       | S4 output           |
| Table name           | string    | "Report" (default)  |
| Simulation filter    | string    | Optional regex      |

## Outputs

| Output               | Format     | Description                          |
|----------------------|-----------|--------------------------------------|
| Results CSV          | .csv      | Tabular results with headers         |
| Parse report         | JSON      | Table info, row counts, warnings     |

## Procedure

1. **List available tables** (optional):
   ```bash
   python parse_output.py --db simulation.db --list-tables
   ```
   Common tables:
   - `Report` — Main output (user-defined variables)
   - `DailyReport` — Daily summary (if configured)
   - `_Simulations` — Simulation metadata
   - `_Units` — Variable unit information
   - `_Messages` — Log messages (errors, warnings)
   - `_Checkpoints` — Checkpoint data

2. **Extract data**:
   ```bash
   python parse_output.py --db simulation.db --output results.csv \
       --table Report --convert-yield
   ```

3. **Unit conversions** (with `--convert-yield`):
   - Biomass (`.Wt`) columns: adds `_kg_ha` column (× 10)
   - Grain yield columns: adds `_t_ha` column (÷ 100)
   - Example: `Wheat.Grain.Wt` = 350 g/m²
     → `Wheat.Grain.Wt_kg_ha` = 3500 kg/ha
     → `Wheat.Grain.Wt_t_ha` = 3.50 t/ha

4. **Direct SQL access** (alternative):
   ```bash
   sqlite3 -header -csv simulation.db \
       "SELECT * FROM Report WHERE SimulationID=1"
   ```

## Verification

- [ ] CSV has expected number of rows (daily records × simulations)
- [ ] Date column spans the full simulation period
- [ ] Grain yield values are in expected range for the crop and region
- [ ] No entirely NULL columns (suggests Report variable path error)
- [ ] Biomass values make physical sense:
  - Wheat grain: 100-600 g/m² (1-6 t/ha)
  - Wheat biomass: 500-2000 g/m² (5-20 t/ha)
  - Maize grain: 300-1200 g/m² (3-12 t/ha)
  - LAI peak: 3-8 m²/m²

## Traps

- **Biomass in g/m², not kg/ha** (dt_006): The most common misinterpretation.
  APSIM reports all biomass as g/m². Literature and agronomic data typically use
  kg/ha or t/ha. Factor of 10 error if confused.
  - g/m² × 10 = kg/ha
  - g/m² ÷ 100 = t/ha

- **Empty Report table** (dt_015): If the Report.EventNames doesn't trigger,
  no rows are written. Check that `[Clock].DoReport` is in EventNames for
  daily output.

- **Wrong variable path**: `[Wheat].Grain.Wt` works, but `[wheat].grain.wt`
  does not (case-sensitive). Check exact paths in APSIM documentation.

- **Multiple simulations in one file**: If the .apsimx has factorial
  experiments, the output .db contains results for ALL simulations. Use
  `--simulation` filter or check SimulationID column.

- **Checkpoint confusion**: APSIM supports checkpoints (snapshots). The
  CheckpointID column must be filtered if you only want the final run.

## Example

```bash
# Extract and convert
python parse_output.py --db dalby_wheat.db --output results.csv \
    --table Report --convert-yield

# Output summary:
# {
#   "status": "ok",
#   "table": "Report",
#   "n_rows": 1461,
#   "columns": ["SimulationID", "Clock.Today", "Wheat.Grain.Wt",
#                "Wheat.Grain.Wt_kg_ha", "Wheat.Grain.Wt_t_ha", ...],
#   "date_range": "1992-01-01 to 1995-12-31",
#   "warnings": []
# }

# Quick check of grain yield at maturity
sqlite3 dalby_wheat.db \
    "SELECT [Clock.Today], [Wheat.Grain.Wt]*10 as yield_kg_ha
     FROM Report
     WHERE [Wheat.Grain.Wt] > 0
     ORDER BY [Clock.Today]"
```
