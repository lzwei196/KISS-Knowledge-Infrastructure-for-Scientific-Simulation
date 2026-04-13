# Stage 4: Model Execution

## Purpose

Run the FSM2 binary with a namelist file piped to stdin. The model reads
meteorological driving data, simulates snow processes at each timestep, and
writes output files.

## Inputs

| Item | Description |
|------|-------------|
| `FSM2` | Compiled binary (see Stage 3) |
| Namelist file | 6 namelist blocks in order |
| Met forcing file | ASCII file referenced in `&drive` |
| Optional: start file | State dump from previous run |

## Outputs

| File | Content |
|------|---------|
| `{runid}flux.txt` | Energy fluxes: H, LE, LWout, Melt, Roff, subl, SWout |
| `{runid}stat.txt` | State: snd, snw, svg, Tsoil, Tsrf, Tveg |
| `{runid}subc.txt` | Subcanopy: LWsub, SWsub, Tsub, Usub |
| `{runid}dump` | End-of-run state dump (for restart) |

## Procedure

1. **Ensure binary and files are in the same directory** (or use paths in namelist).
2. **Run the model**:
   ```bash
   ./FSM2 < nlst_site.txt
   ```
3. **Check output files** were created and are non-empty.
4. **For restart runs**: use the dump file from a previous run as start_file:
   ```fortran
   &initial
     start_file = 'previous_dump'
   /
   ```

## Runtime Characteristics

- **Speed**: Very fast. 1 year hourly for 1 point < 1 second.
- **Memory**: Minimal (arrays sized by Npnts × Nsmax/Nsoil).
- **Timestep**: Default dt=3600s (1 hour). Must match forcing file interval.
- **No parallelism**: Single-threaded Fortran. Multi-point runs loop over points.

## Verification

- Output files exist and are non-empty
- Number of output rows = number of input rows
- Check first/last timestamps match forcing period
- Snow depth (snd) should:
  - Be 0 at start of accumulation season
  - Increase during snowfall events
  - Decrease during melt
  - Return to 0 by end of melt season
- Surface temperature Tsrf should not exceed 273.15 K when snow is present

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Met file not found | Runtime error: "file not found" | Check path in `&drive` |
| Namelist blocks in wrong order | Fortran namelist read error | Maintain order: params, gridpnts, gridlevs, drive, veg, initial, outputs |
| dt mismatch | Wrong accumulation rates | Ensure dt matches forcing interval |
| Npnts mismatch with veg arrays | Array bounds error | Match Npnts with number of values in &veg |
| Binary not executable | Permission denied | `chmod +x FSM2` |
| Met file has header row | Parse error on first line | Remove header (FSM2 reads year as first token) |
| Empty namelist blocks omitted | Missing values, defaults may be wrong | Include all blocks, even empty: `&gridlevs /` |

## Example

```python
from ki.tools.run_fsm2 import compile_and_run

result = compile_and_run(
    source_dir="/path/to/FSM2/source/repo",
    namelist_file="/path/to/nlst_site.txt",
    run_dir="/path/to/run/",
)
print(f"Status: {result['status']}")
```

## Multi-Point Runs

FSM2 supports multiple points in a single run. Set `Npnts = N` in `&gridpnts`
and provide N values for each variable in `&veg`:

```fortran
&gridpnts
  Npnts = 2
/
&veg
  alb0 = 0.15, 0.15
  vegh = 0.00, 25.0
  VAI  = 0.00, 3.96
/
```

All points share the same forcing data but can have different vegetation. Output
files contain columns for all points concatenated per row.
