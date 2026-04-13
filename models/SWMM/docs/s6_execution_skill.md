# SWMM Execution and Results Extraction — Skill Document

> **Stage ID**: s6_execution
> **Pipeline order**: 6 of 7
> **Depends on**: s5_model_assembly

## Purpose

This stage runs the SWMM simulation and extracts results. SWMM's C engine performs the hydraulic and hydrologic computations, producing a binary output (OUT) file and a text report (RPT) file. The RPT file contains summary statistics, continuity errors, and diagnostic messages. The OUT file contains detailed time series for every node, link, and subcatchment.

After execution, continuity errors must be checked to verify numerical stability. Results are then extracted for analysis, plotting, and comparison with observed data or other models.

## Prerequisites

Before starting this stage, verify:

- [ ] INP file exists and passes validation (S5 complete)
- [ ] pyswmm is installed: `pip install pyswmm`
- [ ] Output directory exists and is writable
- [ ] Sufficient disk space for OUT file (can be large for long simulations with many elements)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| INP file | file | S5 output | Complete, validated SWMM input file |
| Output paths | config | User choice | Paths for RPT and OUT files |
| Extract config | config | User choice | Which nodes, links, subcatchments to extract |

## Procedure

### Step 1: Run the SWMM Simulation

```bash
python tools/s6_execution/run_swmm.py \
  --inp_file outputs/swmm_run/model.inp \
  --rpt_file outputs/swmm_run/model.rpt \
  --out_file outputs/swmm_run/model.out
```

The tool uses pyswmm internally:

```python
from pyswmm import Simulation

with Simulation("model.inp", "model.rpt", "model.out") as sim:
    for step in sim:
        pass  # Simulation advances step by step
```

**Runtime expectations**:
| Model Size | Elements | Period | Routing | Typical Runtime |
|-----------|----------|--------|---------|-----------------|
| Small | 10-50 nodes | 1 day | DYNWAVE | 1-10 seconds |
| Medium | 50-500 nodes | 1 year | DYNWAVE | 1-30 minutes |
| Large | 500-5000 nodes | 1 year | DYNWAVE | 30 min - 4 hours |
| Very large | 5000+ nodes | 1 year | DYNWAVE | 4-24 hours |

Dynamic wave is 5-10x slower than kinematic wave. Reducing the routing timestep increases runtime proportionally.

**Do NOT interrupt the simulation** once started. If the process seems stuck, check CPU usage — SWMM is CPU-bound and may not produce output for minutes during long simulations.

### Step 2: Check for Errors in RPT File

After simulation completes, immediately check the RPT file for errors:

```bash
python tools/s6_execution/check_continuity_errors.py \
  --rpt_file outputs/swmm_run/model.rpt
```

The tool extracts:

**Continuity errors** (most important):
- **Runoff quantity continuity error**: Difference between total rainfall and total runoff + infiltration + evaporation + storage change. Should be < 5%.
- **Flow routing continuity error**: Difference between total inflow and total outflow + storage change in the drainage network. Should be < 5% (< 1% for dynamic wave).

**Node flooding summary**: Which nodes flooded, total volume flooded, maximum ponded depth. Flooding is expected during design storms but should be physically reasonable.

**Conduit surcharging summary**: Which conduits were pressurized (flowing full). Persistent surcharging in many conduits suggests the system is undersized for the storm.

**Outfall loading summary**: Total volume and peak flow at each outfall. This is the primary output for comparison with downstream models.

### Step 3: Interpret Continuity Errors

| Error Range | Status | Action |
|-------------|--------|--------|
| < 0.5% | Excellent | No action needed |
| 0.5 - 1% | Good | Acceptable for most analyses |
| 1 - 5% | Acceptable | Investigate if possible; reduce timestep |
| 5 - 10% | Poor | Reduce routing timestep; check for adverse slopes |
| > 10% | Unacceptable | Model is numerically unstable; fix before using results |

**High routing continuity error causes and fixes**:
1. **Routing timestep too large**: Reduce WET_STEP and ROUTING_STEP (dt_001)
2. **Adverse conduit slopes**: Fix invert elevations or remove adverse slopes (dt_002)
3. **Very short conduits**: Minimum conduit length should be > 10m for dynamic wave
4. **Extreme inflows**: Check that external inflows are in correct units (dt_010)
5. **ALLOW_PONDING=NO with flooding**: Surface flooding water is lost, showing as negative routing error (dt_003)

### Step 4: Extract Results

```bash
python tools/s6_execution/extract_results.py \
  --out_file outputs/swmm_run/model.out \
  --extract_config '{"nodes": ["OF1", "J1"], "links": ["C1"], "subcatchments": ["S1"], "system": true}' \
  --output_format csv \
  --output_dir outputs/swmm_run/results/
```

Available result variables:

**Node results**:
| Variable | Description | Units (CMS) |
|----------|-------------|-------------|
| Depth | Water depth above invert | meters |
| Head | Hydraulic head (invert + depth) | meters |
| Volume | Stored water volume | m3 |
| Lateral_Inflow | Direct inflow from subcatchments | m3/s |
| Total_Inflow | Total inflow from all sources | m3/s |
| Flooding | Overflow rate (if flooded) | m3/s |

**Link results**:
| Variable | Description | Units (CMS) |
|----------|-------------|-------------|
| Flow | Flow rate | m3/s |
| Depth | Flow depth | meters |
| Velocity | Flow velocity | m/s |
| Volume | Water volume in link | m3 |
| Capacity | Fraction of full capacity used | fraction |

**Subcatchment results**:
| Variable | Description | Units (CMS) |
|----------|-------------|-------------|
| Rainfall | Rainfall rate | mm/hr |
| Snow_Depth | Snow depth | mm |
| Evaporation | Evaporation + infiltration loss | mm/hr |
| Infiltration | Infiltration rate | mm/hr |
| Runoff | Surface runoff rate | m3/s |
| GW_Outflow | Groundwater discharge | m3/s |

**System results**: Aggregate totals for the entire system.

### Step 5: Post-Process Results

Extract outfall discharge for comparison with CaMa-Flood or observed data:

```python
import pandas as pd
# Read extracted CSV
df = pd.read_csv("outputs/swmm_run/results/node_OF1_results.csv")
# Outfall discharge = total inflow at outfall node
outfall_Q = df[["datetime", "Total_Inflow"]].copy()
outfall_Q.columns = ["datetime", "Q_m3s"]
outfall_Q.to_csv("outputs/swmm_run/results/outfall_discharge.csv", index=False)
```

## Expected Outputs

| Output | Path Pattern | Description |
|--------|-------------|-------------|
| RPT file | `{output_dir}/model.rpt` | Simulation report with summary and errors |
| OUT file | `{output_dir}/model.out` | Binary results file |
| Continuity report | (stdout/JSON) | Parsed continuity errors and flooding stats |
| Result CSVs | `{output_dir}/results/*.csv` | Extracted time series |

## Validation Checks

1. **No ERROR lines in RPT**: Any line starting with "ERROR" indicates a fatal issue
2. **Runoff continuity < 5%**: Higher suggests subcatchment parameter issues
3. **Routing continuity < 5%** (< 1% for DYNWAVE): Higher suggests timestep or network issues
4. **Outfall flow > 0**: At least some flow should reach the outfall during wet weather
5. **Peak flow plausible**: Compare against rational method estimate (Q = C*i*A) for sanity check
6. **No NaN in results**: NaN values indicate numerical instability
7. **Mass balance**: Total system inflow ~ total system outflow + storage change

## Common Pitfalls

**High routing continuity error (dt_001)**: Most common issue with dynamic wave. Reduce ROUTING_STEP from 30s to 15s, then to 10s, then to 5s until error < 1%. Each reduction approximately doubles runtime.

**Unstable oscillating flow (dt_002)**: Adverse conduit slopes (water flowing uphill) cause flow direction to oscillate every timestep in dynamic wave. Symptoms: alternating positive/negative flows, high continuity error, unreasonable velocities. Fix: correct invert elevations to eliminate adverse slopes, or switch to kinematic wave (which cannot handle adverse slopes and skips the conduit).

**Node flooding with water loss (dt_003)**: Default ALLOW_PONDING=NO means flooded water disappears. For continuous simulations, always set ALLOW_PONDING=YES and define Aponded > 0 for nodes that may flood.

**Dynamic wave surcharging oscillation (dt_017)**: When many conduits alternate between free-surface and pressurized flow, the routing can oscillate. Reduce timestep or increase the VARIABLE_STEP setting to allow adaptive timestep control.

**pyswmm version incompatibility (dt_018)**: Different pyswmm versions bundle different SWMM engine versions. An INP file created for SWMM 5.2 may not work with pyswmm built against SWMM 5.1. Check `pyswmm.__version__` and ensure compatibility.

**OUT file too large**: For year-long simulations with 5-minute reporting and 1000+ elements, the OUT file can exceed 10 GB. Use selective reporting ([REPORT] section) to reduce output size. Only report elements of interest.

## Tools Reference

| Tool ID | Script | Purpose |
|---------|--------|---------|
| `run_swmm` | `tools/s6_execution/run_swmm.py` | Execute SWMM simulation |
| `extract_results` | `tools/s6_execution/extract_results.py` | Extract time series from OUT file |
| `check_continuity_errors` | `tools/s6_execution/check_continuity_errors.py` | Parse RPT for continuity and flooding |
