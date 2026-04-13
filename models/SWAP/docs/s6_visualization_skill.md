# S6: SWAP Visualization and Validation

## Purpose
Generate publication-quality plots of SWAP simulation results and compare against observations for model validation.

## Inputs
- **Parsed CSV files**: water_balance.csv, daily_increments.csv, swap_timeseries.csv
- **Observation data** (optional): Soil moisture, groundwater level, ET measurements
- **Site metadata**: Name, coordinates, period

## Outputs
- `water_balance.png`: Annual water balance bar chart
- `daily_fluxes.png`: Daily rainfall and ET timeseries
- `soil_moisture_profile.png`: Depth profiles at selected dates
- `s8_validation.png`: Observed vs simulated scatter plot with metrics

## Procedure
1. **Water balance plot**:
   - Stacked bar chart: positive (rainfall, irrigation) vs negative (ET, drainage, runoff)
   - One group per year
   - Display storage change as residual

2. **Daily fluxes plot**:
   - Upper panel: Rainfall (inverted bars, blue)
   - Lower panel: Transpiration (red line) + soil evaporation (orange line)
   - X-axis: days or dates

3. **Soil moisture profiles**:
   - Depth on y-axis (inverted, surface at top)
   - Theta on x-axis
   - Multiple lines for different dates

4. **Validation plot**:
   - Scatter: observed (x) vs simulated (y)
   - 1:1 line (dashed black)
   - Metrics box: N, Bias, RMSE, R, NSE
   - Colors: observed = black, simulated = #2563EB

## Verification
- All figures saved as PNG at 150+ DPI
- Axes labeled with units
- Legend present
- No clipped data points
- Metrics computed correctly (especially NSE denominator)

## Traps

### TRAP 1: Unit mismatch in plots
SWAP outputs in cm; observations may be in mm. Always verify units before comparing. Multiply SWAP cm by 10 to get mm.

### TRAP 2: Temporal alignment
SWAP daily output at end of day; observations may be at different times. For soil moisture, ensure measurement depth matches SWAP compartment.

### TRAP 3: NSE sensitivity to mean
NSE is sensitive to the observed mean. For nearly constant series, NSE can be very negative even with small errors. Use KGE as alternative.

### TRAP 4: Matplotlib backend
On headless servers, set `matplotlib.use("Agg")` before importing pyplot, or plots will fail with "no display" error.

### TRAP 5: Observation depth matching
SWAP reports soil moisture per compartment (centered depth). If observation is at 10 cm, match to the SWAP compartment whose center is closest to 10 cm, not the compartment boundary.

## Example
```python
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.scatter(obs, sim, c="#2563EB", s=20, alpha=0.6)
ax.plot([0, 1], [0, 1], "k--")
ax.set_xlabel("Observed θ (cm³/cm³)")
ax.set_ylabel("Simulated θ (cm³/cm³)")
# Add metrics box
ax.text(0.05, 0.95, f"RMSE={rmse:.3f}\nNSE={nse:.3f}",
        transform=ax.transAxes, va="top",
        bbox=dict(boxstyle="round", facecolor="wheat"))
plt.savefig("validation.png", dpi=150)
```
