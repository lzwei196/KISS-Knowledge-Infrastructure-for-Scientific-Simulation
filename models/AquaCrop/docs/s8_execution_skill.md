# Model Execution -- Skill Document

> **Stage ID**: s8_execution
> **Pipeline order**: 8 of 10
> **Depends on**: s7_model_assembly

## Purpose

Execute the AquaCrop simulation. The model steps through each day, computing canopy development, transpiration, soil water balance, biomass accumulation, and yield formation. Unlike VIC or DSSAT (external executables with file I/O), AquaCrop-OSPy runs entirely in-memory as Python code.

## Prerequisites

- [ ] AquaCropModel assembled (S7 complete)
- [ ] No unresolved validation warnings from S7

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| model | AquaCropModel | S7 | Assembled model object |

## Procedure

### Step 1: Run to completion

```python
success = model.run_model(till_termination=True)
assert success == True, "Model did not complete"
```

### Step 2: Alternative -- step-by-step execution

For real-time applications or progress monitoring:

```python
# Initialize and run first 30 days:
model.run_model(num_steps=30, initialize_model=True)
# Continue for 30 more days:
model.run_model(num_steps=30, initialize_model=False)
# Run to end:
model.run_model(till_termination=True, initialize_model=False)
```

### Step 3: Check completion

```python
info = model.get_additional_information()
print(f"Finished: {info['has_model_finished']}")
print(f"Runtime: {info['execution_time']:.2f} seconds")
```

### Step 4: Verify outputs exist

```python
final = model.get_simulation_results()
assert final is not False, "Model not finished (get_simulation_results returned False)"
assert len(final) > 0, "No seasonal results -- check if crop reached harvest"
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Execution success | boolean | `run_model()` returns True |
| Output DataFrames | in-memory | `get_simulation_results()` returns DataFrame |

## Validation Checks

1. **Return value**: `run_model()` returns True
   - If False or exception: Check dt_014 (zero yield scenarios)

2. **Results available**: `get_simulation_results()` returns DataFrame, not False
   - If False: Model has not finished. Run more steps.

3. **Yield sanity**: `Dry yield > 0` for at least one season
   - If zero: See dt_014 for silent crop death causes

## Common Pitfalls

> **PITFALL**: Calling get_simulation_results() before model finishes
> If run_model() was called with num_steps (not till_termination) and the model has not reached the end, get_simulation_results() returns False.
> **Do this instead**: Either use `till_termination=True`, or check `get_additional_information()['has_model_finished']` before accessing results.

> **PITFALL**: Calling run_model() twice with initialize_model=True
> The second call reinitializes the model, losing all previous simulation state.
> **Do this instead**: Set `initialize_model=False` for subsequent calls.

> **PITFALL**: Silent crop death
> The model may run to completion with yield=0 if the crop dies from extreme water stress, heat stress, or waterlogging. No error is raised.
> **Do this instead**: Check canopy_cover trajectory in crop_growth output. If canopy never develops, the crop died.
> See diagnostic triplet dt_008, dt_014.

---

*This skill document is part of the aquacrop-ospy-knowledge infrastructure.*
*Stage 8 of 10 | Tools used: run_aquacrop | Related triplets: dt_008, dt_014*
