# S6: Output Analysis

## Purpose

Extract, visualize, and validate results from TELEMAC SELAFIN output files.
Convert binary results to accessible formats (CSV, plots) and compare against
observations or analytic solutions.

## Inputs

| Input                | Format   | Description                                 |
|----------------------|----------|---------------------------------------------|
| Results file         | .slf     | SELAFIN output from Stage 5                 |
| Observation data     | CSV      | Gauge measurements for validation           |
| Analytic solution    | Python   | Reference solution (for test cases)         |

## Outputs

| Output               | Format   | Description                                 |
|----------------------|----------|---------------------------------------------|
| Time-series CSV      | .csv     | Extracted variables at selected nodes       |
| Spatial snapshot CSV | .csv     | All nodes at a single timestep              |
| Validation plots     | .png     | Comparison with observations / analytics    |
| Statistics report    | JSON     | RMSE, bias, Nash-Sutcliffe, etc.            |

## Procedure

1. **Inspect output metadata**:
   ```bash
   python parse_selafin.py results.slf --info
   ```
   Verify: correct number of timesteps, expected variables, reasonable ranges.

2. **Extract time series at gauge locations**:
   ```bash
   python parse_selafin.py results.slf \
       --variables H,U,V --nodes 150,275,400 \
       --output gauge_timeseries.csv
   ```

3. **Extract spatial snapshot**:
   ```bash
   python parse_selafin.py results.slf \
       --timestep -1 --variables H,S,B \
       --output final_state.csv
   ```

4. **Compute validation metrics**:
   ```python
   import numpy as np
   obs = np.loadtxt("observed.csv", delimiter=",", skiprows=1)
   sim = np.loadtxt("simulated.csv", delimiter=",", skiprows=1)

   # RMSE
   rmse = np.sqrt(np.mean((sim - obs)**2))

   # Nash-Sutcliffe Efficiency
   nse = 1 - np.sum((sim - obs)**2) / np.sum((obs - np.mean(obs))**2)

   # Bias
   bias = np.mean(sim - obs)
   ```

5. **Visualize results**:
   - Time series: simulated vs observed at gauge points
   - Spatial maps: water depth, velocity vectors, Froude number
   - Profile plots: along-channel water surface profile
   - Use TELEMAC's built-in postel3d or external tools (ParaView, QGIS)

## Verification

- [ ] Time series show physically reasonable values
- [ ] No persistent NaN or extreme values in extracted data
- [ ] Mass balance error (from listing) < acceptable threshold
- [ ] Tidal phase and amplitude match observations (coastal cases)
- [ ] Steady-state cases have converged (values stabilized)

## Traps

- **dt_018**: Variable order mismatch. If custom variables were added,
  the column order in the CSV may not match expectations. Always check
  the variable names in the SELAFIN header.

- **dt_013**: Custom SELAFIN parsers must handle big-endian byte order.
  Use the provided parse_selafin.py or the hermes Python wrapper.

- Comparing at wrong node IDs: SELAFIN node numbering is 0-based in Python
  but 1-based in TELEMAC Fortran listings. Subtract 1 when specifying nodes.

## Example

```bash
# Complete post-processing workflow for bump test case
cd examples/telemac2d/bump

# 1. Run the simulation
telemac2d.py t2d_bump_FE.cas

# 2. Inspect results
python parse_selafin.py r2d_bump.slf --info

# 3. Extract centerline profile at final timestep
python parse_selafin.py r2d_bump.slf \
    --variables H,S,B --timestep -1 \
    --output bump_final.csv

# 4. Compare with analytic solution
python analytic_sol.py  # generates ANALYTIC_SOL.txt

# 5. Compute RMSE
python -c "
import numpy as np
sim = np.loadtxt('bump_final.csv', delimiter=',', skiprows=1)
ana = np.loadtxt('ANALYTIC_SOL.txt')
# Compare water depth (H) at matching X positions
rmse = np.sqrt(np.mean((sim[:,3] - ana[:,1])**2))
print(f'RMSE(H) = {rmse:.6f} m')
"
```
