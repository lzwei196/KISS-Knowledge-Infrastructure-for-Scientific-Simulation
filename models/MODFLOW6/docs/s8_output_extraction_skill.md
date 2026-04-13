# Head & Budget Extraction — Skill Document

> **Stage ID**: s8_output_extraction
> **Pipeline order**: 8 of 9
> **Depends on**: s7_execution

## Purpose

Read the binary output files produced by MODFLOW 6 (.hds for heads, .cbc for cell budgets) and extract meaningful data: head arrays per timestep, water table elevation, budget terms by component. This is the bridge between raw MODFLOW output and analysis/visualization. Proper handling of dry cells (HDRY sentinel values) and budget sign conventions is critical.

## Prerequisites

Before starting this stage, verify:

- [ ] Simulation completed successfully with "Normal termination" (S7 complete)
- [ ] gwf.hds and gwf.cbc files exist and are non-empty
- [ ] FloPy is available for reading binary files

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| hds_path | file | S7 output | Binary head file (gwf.hds) |
| cbc_path | file | S7 output | Cell budget file (gwf.cbc) |
| model_path | directory | workspace | For grid dimensions |

## Procedure

### Step 1: Read Binary Head File

```bash
python tools/s8/extract_heads.py
```

Using FloPy directly:
```python
import flopy.utils.binaryfile as bf

hds = bf.HeadFile("workspace/gwf.hds")

# List available time steps
hds.list_records()

# Get heads for specific timestep/period (0-indexed)
heads = hds.get_data(kstpkper=(0, 0))  # First timestep of first period
# Shape: (nlay, nrow, ncol)

# Get all timesteps
all_times = hds.get_times()
for t in all_times:
    h = hds.get_data(totim=t)
```

**Expected result**: Head arrays with shape (nlay, nrow, ncol).

### Step 2: Handle Dry Cells (HDRY)

MODFLOW 6 uses a sentinel value for dry cells: **1.0e30** (HDRY). These are NOT real head values. They must be masked before any analysis.

```python
import numpy as np

HDRY = 1.0e30
heads_masked = np.where(heads > 0.9e30, np.nan, heads)
# Or:
heads_masked = np.ma.masked_where(heads > 0.9e30, heads)
```

**Count dry cells**:
```python
dry_count = (heads > 0.9e30).sum()
print(f"Dry cells: {dry_count}")
```

**If many dry cells**: See dt_mf6_002.

### Step 3: Extract Water Table

The water table is the head in the topmost active (non-dry) cell in each column:

```python
water_table = np.full((nrow, ncol), np.nan)
for i in range(nrow):
    for j in range(ncol):
        for k in range(nlay):
            if heads[k, i, j] < 0.9e30 and idomain[k, i, j] > 0:
                water_table[i, j] = heads[k, i, j]
                break
```

Or use FloPy's utility:
```python
water_table = flopy.utils.postprocessing.get_water_table(heads, nodata=1e30)
```

**Expected result**: 2D array of water table elevations.

### Step 4: Read Cell Budget File

```bash
python tools/s8/extract_budget.py
```

Using FloPy:
```python
cbb = bf.CellBudgetFile("workspace/gwf.cbc")

# List available budget terms
cbb.list_records()
# Typical terms: 'STO-SS', 'STO-SY', 'FLOW-JA-FACE', 'CHD', 'RCH', 'DRN', 'RIV', 'WEL'

# Get specific term
rch_flux = cbb.get_data(kstpkper=(0, 0), text="RCH")
drn_flux = cbb.get_data(kstpkper=(0, 0), text="DRN")
```

**Budget sign convention**:
- **Positive** = water entering the model (inflow)
- **Negative** = water leaving the model (outflow)
- RCH is positive (water enters from surface)
- DRN is negative (water leaves to drains)
- WEL is negative for pumping, positive for injection

### Step 5: Check Budget Balance

Read budget summary from listing file:

```python
# Parse listing file for budget
with open("workspace/gwf.lst") as f:
    content = f.read()
    # Find "VOLUME BUDGET" sections
    # Check "PERCENT DISCREPANCY"
```

Or compute from budget file:
```python
total_in = sum(flux[flux > 0].sum() for flux in all_fluxes)
total_out = sum(abs(flux[flux < 0].sum()) for flux in all_fluxes)
pct_disc = 100 * (total_in - total_out) / ((total_in + total_out) / 2)
print(f"Budget discrepancy: {pct_disc:.4f}%")
```

**Expected result**: Percent discrepancy < 0.1%.

**If discrepancy > 1%**: See dt_mf6_003.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Head arrays | in memory / JSON | Correct shape (nlay, nrow, ncol), no unexpected HDRY |
| Water table | in memory / JSON | 2D array, values between BOTM and TOP |
| Budget terms | in memory / JSON | Terms sum to near-zero discrepancy |

## Validation Checks

1. **No HDRY in active cells** (unless expected dry areas):
   - Expected: Dry cell count < 5% of active cells
   - If unexpected: See dt_mf6_002

2. **Head values physically reasonable**:
   - Expected: min(head) > min(BOTM) and max(head) < max(TOP) + 10 m
   - If unexpected: Boundary conditions may be wrong

3. **Budget balance**:
   - Expected: Percent discrepancy < 0.1%
   - If unexpected: See dt_mf6_003

4. **Head file records match expected timesteps**:
   - Expected: Number of records = sum(NSTP for all periods)
   - If unexpected: Simulation may have stopped early

## Common Pitfalls

> **PITFALL**: Not masking HDRY sentinel values
> HDRY = 1e30 will corrupt statistics (mean, max, min, contours) if included as real head values. A "mean head of 1e28" is clearly wrong, but subtler corruption occurs when only a few cells are dry.
> **Do this instead**: Always mask heads > 0.9e30 as NaN before any analysis.
> See diagnostic triplet dt_mf6_006.

> **PITFALL**: Wrong kstpkper indexing
> FloPy uses 0-based indices for kstpkper: (0, 0) is the first timestep of the first period. MODFLOW listing files use 1-based. Requesting kstpkper=(1, 1) gives the second timestep of the second period.
> **Do this instead**: Use 0-based indexing consistently in FloPy. Cross-reference with `hds.list_records()`.
> See diagnostic triplet dt_mf6_006.

> **PITFALL**: Assuming budget text strings match exactly
> Budget term names have trailing spaces in the binary file. FloPy handles this internally, but if searching raw records, use stripped comparison.
> **Do this instead**: Use `cbb.get_data(text="RCH")` — FloPy strips whitespace automatically.

> **PITFALL**: Confusing budget sign convention
> DRN and WEL extraction fluxes are negative (outflow). When converting to baseflow for routing, negate: `baseflow = -drn_flux`.
> See diagnostic triplet dt_mf6_015.

---

*This skill document is part of the modflow6-knowledge-infrastructure package.*
*Stage 8 of 9 | Tools used: extract_heads, extract_budget | Related triplets: dt_mf6_002, dt_mf6_003, dt_mf6_006, dt_mf6_015*
