# Stage 5: Output Analysis and Validation

## Purpose

Parse FSM2 ASCII output files, compute snow metrics, and validate results
against observations or published values.

## Inputs

| File | Content |
|------|---------|
| `{runid}flux.txt` | Energy fluxes (H, LE, LWout, Melt, Roff, subl, SWout) |
| `{runid}stat.txt` | State variables (snd, snw, svg, Tsoil, Tsrf, Tveg) |
| `{runid}subc.txt` | Subcanopy diagnostics (LWsub, SWsub, Tsub, Usub) |
| Observations | Snow depth, SWE, temperature measurements |

## Outputs

- Merged CSV with all variables and datetime index
- Validation plots (time series, scatter)
- Performance metrics

## Procedure

1. **Parse output** using `parse_fsm2_output.py`:
   ```python
   from ki.tools.parse_fsm2_output import parse_fsm2_output
   df = parse_fsm2_output("run_dir", runid="test_", output_csv="output.csv")
   ```

2. **Basic quality checks**:
   - Snow depth (snd) should be ≥ 0
   - SWE (snw) should be ≥ 0
   - Surface temperature ≤ 273.15 K when snd > 0
   - Energy balance: SWin - SWout + LWin - LWout - H - LE ≈ Gsrf

3. **Compute validation metrics** if observations available:

   | Metric | Formula | Good value |
   |--------|---------|------------|
   | RMSE | √(mean((sim-obs)²)) | < 0.1 m (snow depth) |
   | Bias | mean(sim-obs) | < 0.05 m |
   | R² | correlation² | > 0.8 |
   | NSE | 1 - Σ(sim-obs)²/Σ(obs-mean(obs))² | > 0.6 |
   | Peak SWE error | (max(sim) - max(obs))/max(obs) | < 20% |
   | Snow disappearance date error | |sim_date - obs_date| | < 7 days |

4. **Key plots**:
   - Snow depth time series: observed vs simulated
   - SWE time series
   - Surface temperature time series
   - Energy flux components stack plot
   - Snow depth scatter plot with 1:1 line

## Verification

- Output CSV has correct number of rows (= forcing timesteps)
- Date range matches forcing period
- No NaN values in output
- Snow mass balance: cumulative(Sf - Melt - subl - Roff) ≈ snw(t) - snw(0)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Multi-point columns misaligned | Variables mixed between points | Use npnts parameter in parser |
| Missing datetime parsing | No time axis for plots | Construct from year/month/day/hour |
| Units mismatch with obs | Metrics look terrible | Convert obs to FSM2 units (m, kg/m², K) |
| Melt rate in kg/m²/s not mm/day | Values look tiny | Multiply by 86400 to get mm/day |
| Ncnpy mismatch | Wrong number of columns parsed | Check CANMOD option used in compilation |
| Comparing canopy vs open point | Wrong validation | Check which point index matches obs site |

## Example

```python
import matplotlib.pyplot as plt
from ki.tools.parse_fsm2_output import parse_fsm2_output

# Parse multi-point run, extract point 1 (open)
df = parse_fsm2_output(
    "run_dir", runid="Alptal_", npnts=2, point=1,
    output_csv="alptal_open.csv"
)

# Plot snow depth
fig, ax = plt.subplots(figsize=(12, 4))
ax.plot(df["datetime"], df["snd"], color="#2563EB", label="FSM2")
ax.set_ylabel("Snow depth (m)")
ax.set_xlabel("Date")
ax.legend()
plt.savefig("snow_depth.png", dpi=150, bbox_inches="tight")
```

## Energy Balance Check

The surface energy balance should close:

```
SWin - SWout + LWin - LWout - H - LE ≈ G + dS/dt
```

where G is ground heat flux and dS/dt is change in snow energy storage.
Residuals > 10 W/m² suggest a problem with forcing or compilation options.
