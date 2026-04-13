# S4 — Execution

## Purpose

Run the APSIM simulation via the CLI, with preflight validation and post-run
checks to catch common failure modes early.

## Inputs

| Input                | Format     | Source              |
|----------------------|-----------|---------------------|
| Simulation file      | .apsimx   | S3 output           |
| APSIM binary         | executable| Installed APSIM     |
| Run options          | flags     | User configuration  |

## Outputs

| Output               | Format     | Description                          |
|----------------------|-----------|--------------------------------------|
| Output database      | .db       | SQLite with simulation results       |
| CSV exports          | .csv      | Optional CSV per Report table        |
| Run report           | JSON      | Status, timing, warnings             |

## Procedure

1. **Preflight checks** (handled by `run_apsim.py`):
   - APSIM binary exists and is executable
   - .apsimx file is valid JSON
   - Referenced .met files are accessible
   - Sufficient disk space for output

2. **Execute the simulation**:
   ```bash
   # Using pre-built binary
   python run_apsim.py --apsimx simulation.apsimx --binary /path/to/apsim --csv

   # Using dotnet project (build from source)
   python run_apsim.py --apsimx simulation.apsimx \
       --dotnet-project /path/to/ApsimX --csv --verbose

   # Direct CLI (without wrapper)
   apsim run simulation.apsimx --csv --verbose
   ```

3. **Execution options**:
   | Flag                  | Description                              |
   |-----------------------|------------------------------------------|
   | `--csv`               | Export Report tables to CSV              |
   | `--verbose`           | Print simulation start/end messages      |
   | `--single-threaded`   | Run sequentially (easier debugging)      |
   | `--cpu-count N`       | Limit parallel threads                   |
   | `--simulation-names`  | Regex filter for which simulations to run|
   | `--run-tests`         | Execute embedded tests after simulation  |

4. **Post-run validation**:
   - Output .db file exists and is non-empty
   - No FATAL errors in stderr
   - CSV files generated (if --csv used)

## Verification

- [ ] Return code is 0 (success)
- [ ] Output .db file exists and size > 1000 bytes
- [ ] No NullReferenceException in stderr
- [ ] No "Could not find" errors in stderr
- [ ] Simulation completed in reasonable time (< 60s per year per crop)

## Traps

- **Binary not found** (dt_012): If building from source, the binary is at
  `APSIM.Cli/bin/Release/net8.0/apsim`. Common mistake: looking for `apsim.exe`
  on Linux (it's just `apsim` with no extension).

- **Missing .NET runtime**: APSIM requires .NET 8.0 runtime. Install with
  `sudo apt-get install dotnet-runtime-8.0`.

- **.met file path broken** (dt_004): Most common runtime error. Check that
  %root% resolves correctly and the .met file exists at the resolved path.

- **SQLite locked** (dt_014): If a previous run crashed, the .db-wal and
  .db-shm files may persist. Delete them before re-running.

- **Out of memory**: Large factorial experiments can exhaust memory. Use
  `--cpu-count 1` to reduce memory footprint, or split into smaller batches.

- **Silent failure**: APSIM may report success (return code 0) even if
  individual simulations failed. Check the _Messages table in the .db for
  errors: `sqlite3 output.db "SELECT * FROM _Messages WHERE MessageType=2"`

## Example

```bash
# Full pipeline execution
python run_apsim.py --apsimx dalby_wheat.apsimx \
    --binary /opt/apsim/bin/apsim \
    --csv --verbose --timeout 600

# Expected output:
# {
#   "status": "ok",
#   "return_code": 0,
#   "elapsed_s": 12.3,
#   "output_db": "/path/to/dalby_wheat.db",
#   "output_db_size_bytes": 245760,
#   "csv_files": ["/path/to/dalby_wheat.Report.csv"],
#   "warnings": []
# }
```
