# Calibration and Troubleshooting Guide

## Purpose

Systematic approach to calibrating EPANET models against observed field data, diagnosing common simulation failures, and resolving convergence issues. This document covers the iterative calibration workflow and provides a troubleshooting decision tree.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Simulated results | Stage 8 (parse_epanet_output) | CSV |
| Observed pressures | SCADA, pressure loggers | CSV time series (psi or m) |
| Observed flows | Flow meters, SCADA | CSV time series (GPM or LPS) |
| Observed tank levels | SCADA, level sensors | CSV time series (ft or m) |
| Observed quality | Water quality monitors, grab samples | CSV (mg/L) |

## Outputs

| Output | Format | Used By |
|--------|--------|---------|
| Calibrated .inp file | EPANET text input | Production simulation |
| Calibration metrics | JSON/CSV | Documentation |
| Diagnostic plots | PNG | Reporting |

## Procedure

### 1. Calibration Target Priorities

Calibrate in this order:
1. **Tank levels** — Most constrained, easiest to validate
2. **System pressures** — At known metering points
3. **Pipe flows** — At flow measurement stations
4. **Water quality** — Chlorine residuals at monitoring points

### 2. Calibration Parameters (Sensitivity Order)

| Parameter | Sensitivity | Typical Adjustment Range |
|-----------|-------------|-------------------------|
| Demand multiplier | HIGH | 0.5 - 2.0× |
| Pipe roughness (C-factor) | HIGH | ±30% of estimated value |
| Demand pattern shape | MEDIUM | Peak/trough timing and magnitude |
| Pump curve | MEDIUM | ±10% of rated flow/head |
| Minor loss coefficients | LOW | 0 - 10 |
| Reservoir head pattern | LOW | ±5% of nominal head |

### 3. Iterative Calibration Workflow

```
Step 1: Match total system demand (adjust DEMAND MULTIPLIER)
   → Target: total pump flow ≈ observed total flow (±5%)

Step 2: Adjust spatial demand distribution
   → Target: tank filling/draining matches SCADA levels

Step 3: Calibrate roughness coefficients
   → Target: pressure at monitoring points matches observed (±5 psi / 3.5 m)

Step 4: Fine-tune demand patterns
   → Target: diurnal pressure variation matches observed pattern

Step 5: Validate water quality (if applicable)
   → Target: chlorine residuals at monitoring points (±0.2 mg/L)
```

### 4. Acceptance Criteria

| Metric | Excellent | Acceptable | Poor |
|--------|-----------|------------|------|
| Pressure RMSE | < 2 psi (1.4 m) | < 5 psi (3.5 m) | > 10 psi (7 m) |
| Flow RMSE | < 5% of mean | < 10% of mean | > 20% of mean |
| Tank level RMSE | < 1 ft (0.3 m) | < 3 ft (1 m) | > 5 ft (1.5 m) |
| Chlorine RMSE | < 0.1 mg/L | < 0.3 mg/L | > 0.5 mg/L |
| Pearson R | > 0.95 | > 0.85 | < 0.70 |
| PBIAS | < ±5% | < ±15% | > ±25% |

### 5. Common Simulation Failures

#### Error 110: Cannot Solve Network Hydraulics

**Decision tree**:
1. Is the network connected? → Run connectivity check
2. Is there at least one fixed-grade node (reservoir/tank)? → Add one
3. Are all pipe diameters > 0? → Fix zero-diameter pipes
4. Are there closed pipes isolating parts of the network? → Open or remove
5. Try: increase TRIALS to 500, set UNBALANCED CONTINUE 50

#### Negative Pressures (DDA mode)

**Decision tree**:
1. Are demands realistic? → Check demand multiplier
2. Are elevations correct? → Verify against topographic data
3. Is the supply sufficient? → Check reservoir heads, pump capacity
4. Solution: Switch to PDA demand model

#### Convergence Oscillation

**Symptoms**: Status report shows pump/valve toggling open/closed repeatedly.

**Solutions**:
1. Add hysteresis to controls (e.g., open at level 5, close at level 20, not 5 and 6)
2. Reduce timestep to capture transient behavior
3. Increase DAMPLIMIT to add solution damping
4. Check for conflicting control rules

#### Water Quality Mass Balance Error

**Target**: Mass balance ratio > 0.99 (reported in binary output epilog)

**If poor**:
1. Reduce quality timestep (try 1 minute)
2. Check for very short pipes (< 1 ft) — may cause numerical issues
3. Verify reaction coefficients are reasonable
4. Check source mass injection rates

## Verification

- [ ] Calibrated model reproduces observed tank levels within 1 ft (0.3 m)
- [ ] Pressure errors at monitoring points < 5 psi (3.5 m)
- [ ] Flow errors at metering stations < 10%
- [ ] No negative pressures at any node (or PDA mode active)
- [ ] No convergence warnings in report file
- [ ] Water quality mass balance > 0.95

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| **Over-calibrating roughness** | Perfect fit at calibration points, poor at others | Limit roughness range to physically realistic values |
| **Compensating errors** | Right answer for wrong reasons (demand × roughness) | Calibrate demands first with flow data, then roughness |
| **Steady-state bias** | Good at peak, bad at low demand (or vice versa) | Calibrate pattern shape, not just magnitude |
| **Ignoring head loss formula** | H-W C=0.015 (meant to be D-W roughness) | Verify headloss formula matches roughness interpretation |
| **Timestamp alignment** | Observed data in different timezone or format | Align all timestamps before comparison |

## Example

Quick calibration check in Python:

```python
import pandas as pd
import numpy as np

sim = pd.read_csv("results/nodes.csv")
obs = pd.read_csv("observed.csv")

# Filter to monitoring node
node = "J42"
s = sim[sim['node_id'] == node].set_index('time_h')['pressure']
o = obs[obs['node_id'] == node].set_index('time_h')['pressure']

# Align and compute metrics
common = s.index.intersection(o.index)
s, o = s.loc[common], o.loc[common]

rmse = np.sqrt(np.mean((s - o)**2))
r = np.corrcoef(s, o)[0, 1]
pbias = 100 * (s - o).sum() / o.sum()

print(f"Node {node}: RMSE={rmse:.2f}, R={r:.4f}, PBIAS={pbias:.1f}%")
```
