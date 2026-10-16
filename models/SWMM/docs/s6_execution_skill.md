# SWMM Execution and Results Extraction — Skill Document

> **Stage ID**: s6_execution
> **Pipeline order**: 6 of 7
> **Depends on**: s5_model_assembly

## Purpose

This stage runs the SWMM simulation and extracts results. SWMM's C engine performs the hydraulic and hydrologic computations, producing a binary output (OUT) file and a text report (RPT) file. The RPT file contains summary statistics, continuity errors, and diagnostic messages. The OUT file contains detailed time series for every node, link, and subcatchment.

After execution, continuity errors must be checked to verify numerical stability. Results are then extracted for analysis, plotting, and comparison with observed data or other models.

The checker reads EPA's `Continuity Error (%) ..... value` report syntax.
Missing, unreadable, NaN or infinite balances are FAIL, never zero. The city
runner sets `continuity_valid: false` and `continuity_error: null`, and exits
unsuccessfully when either required balance is invalid; a finite routing balance
does not validate a NaN runoff balance.
Non-finite component balances and storage depths are serialized as JSON `null`,
with `continuity_has_nan: true`, so web/API clients can read failed-run diagnostics.

The Nanjing NaN was reproduced as an engine initialization defect: SWMM 5.2.4
leaves a snowpack melt value uninitialized on zero-area snow surfaces, then reads
it during runoff calculation. The generated city's unused `empty` snowpack
can therefore produce `0 * NaN`, depending on earlier heap contents. A fresh
process can conceal the defect.

`run_city_swmm.py` now removes that exact inactive template when no temperature
forcing, climate adjustment, initial snow or hotstart is present. Real snow
configurations are preserved. A controlled regression using the real engine
reproduces NaN before this change and finite balance afterward. All 23,974
Nanjing subcatchments retain their original rainfall, infiltration, depression
storage, slopes, roughness and impervious fractions. The runoff-only control
closes at -0.038%. See `dt_snowpack_uninitialized_imelt_20261003`; the earlier
roughness/impervious-overshoot diagnoses are superseded by this evidence.

The allocator used to reproduce the defect exists only in the regression
workspace. It is never installed into the production model. Real snow models
need the engine's missing initialization corrected; removing real snow physics
is not an acceptable workaround.

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
  --inp outputs/swmm_run/model.inp \
  --rpt outputs/swmm_run/model.rpt \
  --out outputs/swmm_run/model.out
```

Both the pyswmm and CLI backends validate the completed report after the engine
finalizes its balances. Missing, non-finite, stale, or greater-than-10% balances
produce a nonzero exit code. The older `--inp_file`, `--rpt_file`, and
`--out_file` spellings remain accepted aliases.

When element IDs are requested, `extract_results.py` reads the binary output
using the installed toolkit's attribute enums and writes one complete CSV row
per reporting time, with columns for every requested element and variable.
Unknown/duplicate IDs, missing time steps, and non-finite data fail before
replacing an existing CSV. A report summary cannot substitute for requested
time series. With no element selectors, the tool extracts available RPT node
and link summaries; the link depth field is explicitly a full-depth ratio.
Section titles are recognised only between the report's `*` rule lines, so an
element ID such as `SummaryPipe` cannot end a table early. With `[FILES] USE
RUNOFF`, EPA prints "Runoff supplied by interface file" and no runoff balance;
the runoff balance is then not required (none is made up) and routing is still
checked. The runoff balance is also not required when the total subcatchment area
is zero (EPA then prints no runoff table). Every continuity block, including
each group of five pollutants, must have its `Continuity Error (%)` row with one value per pollutant
(counted from the `----------` groups on the `*` line below the title; long
pollutant IDs above it can run together), or the check fails.
Reports are read as latin-1 because EPA writes raw bytes such as 0xB3 in some
headers. An unreadable flooding row also fails both the checker and
`run_swmm.py`. With `[REPORT] CONTINUITY NO` EPA prints balances only above 10%,
so the runner cannot check them and stops; set `CONTINUITY YES`.

`check_continuity_errors.py` keeps the worst quality continuity error over all
pollutant blocks (EPA prints pollutants five per block). Runoff-table depths are
reported in mm: a US-unit report prints inches, which are converted with 25.4
mm/inch; an unknown depth unit leaves the depth values empty.

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
  --rpt outputs/swmm_run/model.rpt
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
  --out outputs/swmm_run/model.out \
  --nodes OF1,J1 \
  --links C1 \
  --subcatchments S1 \
  --output_dir outputs/swmm_run/results/
```

The selectors are comma-separated element IDs; output is always CSV
(`node_results.csv`, `link_results.csv`, `subcatchment_results.csv`). There is
no system-results option. With no selectors, the tool reads the RPT Link Flow
and Node Depth summaries instead. Link rows are parsed by link type, as EPA
`statsrpt.c` prints them: conduits have velocity, max/full flow and max/full
depth; pumps have only max/full flow (when a pump curve gives a capacity);
orifices and weirs have only max/full depth; dummy and outlet links have none.
Columns that do not apply stay empty. `link_summary.csv` also records the flow
and velocity units from the report header.

Columns written by `extract_results.py` (one column per requested element ID and
variable, named `<ID>_<variable>`; one row per reporting time in `datetime`).
Values are in the model's own units as stored in the .out file: SI flow units
(CMS, LPS, MLD) give metres, mm/hr and the chosen flow unit; US flow units (CFS,
GPM, MGD) give feet, in/hr and the chosen flow unit.

| File | Variables | Units |
|------|-----------|-------|
| `node_results.csv` | `depth` (water depth above invert), `head` (hydraulic head), `total_inflow`, `flooding` (overflow rate) | length; length; flow unit; flow unit |
| `link_results.csv` | `flow`, `depth`, `velocity` | flow unit; length; length/s |
| `subcatchment_results.csv` | `rainfall`, `runoff`, `infiltration` (loss rate) | depth/hr; flow unit; depth/hr |

Other output variables (node volume, lateral inflow, link volume/capacity, snow,
evaporation, groundwater) are not extracted by this tool, and there is no
system-results file.

### Step 5: Post-Process Results

Extract outfall discharge for comparison with CaMa-Flood or observed data:

```python
import pandas as pd
# Read extracted CSV (from extract_results.py --nodes OF1,...)
df = pd.read_csv("outputs/swmm_run/results/node_results.csv")
# Outfall discharge = total inflow at outfall node, in the model's FLOW_UNITS
outfall_Q = df[["datetime", "OF1_total_inflow"]].copy()
# Only label it m3/s when FLOW_UNITS is CMS; convert first otherwise
# (LPS / 1000, CFS * 0.0283168).
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
