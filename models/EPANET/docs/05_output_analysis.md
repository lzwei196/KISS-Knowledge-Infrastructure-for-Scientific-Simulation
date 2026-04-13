# Stage 8: Output Analysis

## Purpose

Parse EPANET simulation outputs (binary .out file and/or text .rpt file), extract time-series results for nodes and links, export to CSV for further analysis, and generate diagnostic plots. This stage also supports validation against observed data (pressure measurements, flow metering, water quality sampling).

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Binary output file | Stage 7 (EPANET run) | .out binary (4-byte aligned) |
| Report file | Stage 7 (EPANET run) | .rpt text file |
| Observed data (optional) | SCADA, field measurements | CSV time series |

## Outputs

| Output | Format | Used By |
|--------|--------|---------|
| Node results CSV | time, node_id, demand, head, pressure, quality | Analysis scripts |
| Link results CSV | time, link_id, flow, velocity, headloss, ... | Analysis scripts |
| Summary statistics | JSON/console | Reporting |
| Validation plots | PNG/PDF | Documentation |

## Procedure

### 1. Parse Binary Output

```bash
python tools/parse_epanet_output.py output.out --csv results/ --summary
```

This produces:
- `results/nodes.csv` — All node results for all time periods
- `results/links.csv` — All link results for all time periods
- Console summary of network, timing, and sample values

### 2. Parse Text Report (Fallback)

If no binary output is available:

```bash
python tools/parse_epanet_output.py --rpt report.rpt --csv results/
```

### 3. Examine Key Variables

**Node variables** (per timestep):
| Variable | Unit (US) | Unit (SI) | Description |
|----------|-----------|-----------|-------------|
| Demand | GPM | LPS | Water withdrawal rate |
| Head | ft | m | Hydraulic head (elevation + pressure head) |
| Pressure | psi | m | Gage pressure at node |
| Quality | mg/L or hr | mg/L or hr | Chemical concentration or water age |

**Link variables** (per timestep):
| Variable | Unit (US) | Unit (SI) | Description |
|----------|-----------|-----------|-------------|
| Flow | GPM | LPS | Flow rate (negative = reverse flow) |
| Velocity | ft/s | m/s | Flow velocity |
| Headloss | /1000ft | /1000m | Head loss per 1000 units of length |
| Quality | mg/L | mg/L | Average water quality in link |
| Status | code | code | 0=closed, 3=open, 4=active |
| Setting | varies | varies | Roughness/speed/valve setting |
| Reaction Rate | mass/L/day | mass/L/day | Chemical reaction rate |
| Friction Factor | - | - | Darcy-Weisbach friction factor |

### 4. Validate Against Observations

For model calibration, compare simulated vs. observed:

```python
import pandas as pd
import numpy as np

# Load simulated
sim = pd.read_csv("results/nodes.csv")
sim_j5 = sim[sim['node_id'] == 'J5'][['time_h', 'pressure']]

# Load observed
obs = pd.read_csv("observed_pressure_J5.csv")

# Merge on time
merged = pd.merge(sim_j5, obs, on='time_h', suffixes=('_sim', '_obs'))

# Calculate metrics
residuals = merged['pressure_sim'] - merged['pressure_obs']
rmse = np.sqrt(np.mean(residuals**2))
mae = np.mean(np.abs(residuals))
r = np.corrcoef(merged['pressure_sim'], merged['pressure_obs'])[0, 1]
pbias = 100 * residuals.sum() / merged['pressure_obs'].sum()

print(f"RMSE: {rmse:.2f} psi")
print(f"MAE:  {mae:.2f} psi")
print(f"R:    {r:.4f}")
print(f"PBIAS: {pbias:.1f}%")
```

### 5. Generate Diagnostic Plots

**Pressure time series**:
```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(merged['time_h'], merged['pressure_obs'], 'k-', label='Observed')
ax.plot(merged['time_h'], merged['pressure_sim'], color='#2563EB', label='Simulated')
ax.set_xlabel('Time (hours)')
ax.set_ylabel('Pressure (psi)')
ax.legend()
ax.set_title('Junction J5 Pressure Comparison')

# Add metrics box
metrics_text = f'R = {r:.3f}\nRMSE = {rmse:.2f}\nPBIAS = {pbias:.1f}%'
ax.text(0.98, 0.95, metrics_text, transform=ax.transAxes,
        verticalalignment='top', horizontalalignment='right',
        bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

plt.tight_layout()
plt.savefig('pressure_validation.png', dpi=150)
```

**System-wide pressure map** (at a single timestep):
```python
nodes = pd.read_csv("results/nodes.csv")
t0_nodes = nodes[nodes['time_h'] == 0]
print(f"Min pressure: {t0_nodes['pressure'].min():.1f}")
print(f"Max pressure: {t0_nodes['pressure'].max():.1f}")
print(f"Mean pressure: {t0_nodes['pressure'].mean():.1f}")
```

### 6. Check for Problems

| Check | Good | Bad |
|-------|------|-----|
| Min pressure | > 20 psi (14 m) | < 0 psi (negative = physically impossible in DDA) |
| Max velocity | < 5 ft/s (1.5 m/s) | > 10 ft/s (scouring, noise) |
| Chlorine residual | 0.2-4.0 mg/L | < 0.2 (insufficient disinfection) or > 4.0 (regulatory limit) |
| Water age | < 48 hours | > 72 hours (stale water, quality concerns) |
| Mass balance | > 0.99 | < 0.95 (numerical issues) |

## Verification

- [ ] CSV files contain expected number of time periods
- [ ] Node and link counts match input file
- [ ] No NaN or -1E10 (missing value indicator) in results
- [ ] Pressure values are physically reasonable
- [ ] Flow conservation: total inflow ≈ total demand + storage change
- [ ] Water quality mass balance ratio close to 1.0

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| **-1E10 values in output** | Missing/uninitialized data | Check for EN_MISSING (-1E10) and filter/flag |
| **Pressure in wrong units** | Values seem off by ~14× | US = psi, SI = meters of head; don't mix |
| **Headloss per 1000 units** | Raw headloss values seem small | Values are per 1000 ft or 1000 m, not per unit length |
| **Negative flow = reverse** | Unexpected negative flows | Negative flow means reverse direction (Node2→Node1) |
| **Binary file byte alignment** | Parser crashes or garbled values | All values are 4-byte aligned; use struct.unpack correctly |
| **Report vs binary mismatch** | Different values in .rpt vs .out | Report may use different precision; binary is more accurate |

## Example

```bash
# Full analysis pipeline
python tools/run_epanet.py --inp network.inp --rpt network.rpt --out network.out
python tools/parse_epanet_output.py network.out --csv results/ --summary

# Output:
# EPANET Output Summary
# ============================================================
#   Title:              My Network
#   Nodes:              150
#   Links:              175
#   Flow Units:         GPM
#   Duration:           86400s (24.0h)
#   Reporting Periods:  25
```
