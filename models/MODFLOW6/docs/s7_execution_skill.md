# Model Execution — Skill Document

> **Stage ID**: s7_execution
> **Pipeline order**: 7 of 9
> **Depends on**: s6_solver

## Purpose

Write all FloPy-constructed packages to MODFLOW 6 text input files, execute the mf6 binary, and verify successful completion. This is where the simulation actually runs. The mf6 binary reads input files, solves the flow equations, writes binary output files (.hds, .cbc), and produces a listing file (.lst) with convergence diagnostics, budget summaries, and warnings.

## Prerequisites

Before starting this stage, verify:

- [ ] All required packages are attached to the simulation:
  - Simulation level: TDIS, IMS
  - GWF model level: DIS, NPF, IC, OC, and at least one stress package
- [ ] mf6 binary is available (S1 verified)
- [ ] Output Control (OC) package is defined (to get .hds and .cbc output)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| sim_path | directory | workspace | Simulation workspace directory |
| mf6_path | file | S1 | Path to mf6 executable |

## Procedure

### Step 1: Add Output Control (OC) Package

Before writing, ensure OC is defined to save heads and budgets:

```python
oc = flopy.mf6.ModflowGwfoc(
    gwf,
    head_filerecord="gwf.hds",
    budget_filerecord="gwf.cbc",
    saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    printrecord=[("BUDGET", "LAST")],
)
```

Without OC, mf6 runs but produces no output files.

### Step 2: Write Simulation Files

```python
sim.write_simulation()
```

This creates all MODFLOW 6 input files in the workspace directory:
- `mfsim.nam` (simulation name file)
- `gwf.nam` (model name file)
- One file per package (`.tdis`, `.ims`, `.dis`, `.npf`, `.ic`, `.oc`, etc.)

**Expected result**: All files created in workspace directory.

**Verify**:
```bash
ls workspace/
# Should see: mfsim.nam, gwf.nam, gwf.tdis, gwf.ims, gwf.dis, gwf.npf, gwf.ic, gwf.oc, ...
```

### Step 3: Run MODFLOW 6

```bash
python tools/s7/write_and_run_simulation.py
```

Or via FloPy:
```python
success, buff = sim.run_simulation()
print("Success:", success)
```

Or directly:
```bash
cd workspace && mf6
```

**Runtime estimates**:

| Grid Size | Steady State | 1 Year Monthly | 10 Years Monthly |
|-----------|-------------|----------------|------------------|
| 1,000 cells | < 1 sec | 2-5 sec | 10-30 sec |
| 10,000 cells | 1-5 sec | 10-60 sec | 1-5 min |
| 100,000 cells | 5-30 sec | 1-10 min | 10-60 min |
| 1,000,000 cells | 1-5 min | 10-60 min | 1-6 hours |

### Step 4: Check Listing File for Errors

The listing file is the primary diagnostic. Check these in order:

```bash
# 1. Did it terminate normally?
grep "Normal termination" workspace/mfsim.lst

# 2. Any convergence failures?
grep "FAILED TO CONVERGE" workspace/gwf.lst

# 3. Budget balance
grep "PERCENT DISCREPANCY" workspace/gwf.lst

# 4. Dry cell warnings
grep -c "DRY" workspace/gwf.lst
```

**Expected result**: Normal termination, no convergence failures, percent discrepancy < 0.1%, few or no dry cells.

**If convergence fails**: See dt_mf6_001.
**If many dry cells**: See dt_mf6_002.
**If budget imbalance**: See dt_mf6_003.

### Step 5: Verify Output Files Exist

```bash
ls -la workspace/gwf.hds workspace/gwf.cbc
```

**Expected result**: Both files exist and have size > 0.

**If files are missing**: OC package was not defined or simulation failed before writing output. See dt_mf6_012.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Head file | `workspace/gwf.hds` | Binary file, size > 0 |
| Budget file | `workspace/gwf.cbc` | Binary file, size > 0 |
| Simulation listing | `workspace/mfsim.lst` | Contains "Normal termination" |
| Model listing | `workspace/gwf.lst` | Budget summaries, convergence info |

## Validation Checks

1. **Normal termination**: Listing file contains "Normal termination of simulation"
   - Command: `grep "Normal termination" mfsim.lst`
   - Expected: String found
   - If unexpected: See dt_mf6_001 or dt_mf6_012

2. **No convergence failures**: Zero occurrences of "FAILED TO CONVERGE"
   - Command: `grep -c "FAILED TO CONVERGE" gwf.lst`
   - Expected: 0
   - If unexpected: See dt_mf6_001

3. **Budget balance**: Percent discrepancy < 0.1%
   - Command: Search for "PERCENT DISCREPANCY" in gwf.lst
   - Expected: All values < 0.1%
   - If unexpected: See dt_mf6_003

4. **Output files exist**: gwf.hds and gwf.cbc have size > 0
   - Command: `ls -la gwf.hds gwf.cbc`
   - Expected: Both files present and non-empty
   - If unexpected: OC package missing or simulation aborted early

## Common Pitfalls

> **PITFALL**: Missing OC package
> If OC is not defined, mf6 runs successfully but writes no .hds or .cbc files. The listing file still has budget information, but there is no spatial head data to extract.
> **Do this instead**: Always add OC with `saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")]`.

> **PITFALL**: Running mf6 from wrong directory
> mf6 reads `mfsim.nam` from the current working directory. If you run mf6 from a different directory, it will not find the name file.
> **Do this instead**: Either `cd workspace && mf6` or use FloPy's `sim.run_simulation()` which handles directory changes.
> See diagnostic triplet dt_mf6_012.

> **PITFALL**: Ignoring convergence warnings
> MODFLOW 6 may converge for most stress periods but fail for a few. The model still produces output, but heads in the failed periods are unreliable.
> **Do this instead**: Always check for "FAILED TO CONVERGE" in the listing file. If convergence failures occur, tighten solver settings or investigate boundary conditions.
> See diagnostic triplet dt_mf6_001.

---

*This skill document is part of the modflow6-knowledge-infrastructure package.*
*Stage 7 of 9 | Tools used: write_and_run_simulation | Related triplets: dt_mf6_001, dt_mf6_002, dt_mf6_003, dt_mf6_012*
