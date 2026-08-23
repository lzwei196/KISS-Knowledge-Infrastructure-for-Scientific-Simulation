# MANDATORY EXECUTION POLICY

Use the real `tools/summarize_rainfall.py` workflow. Never replace it with a
mental calculation or claim an output that was not written. Validate inputs,
run the tool, inspect the output CSV, and report failures with their exact fix.

# Rainfall summary task KI

This KI turns a daily precipitation CSV into monthly totals. It is a task
workflow, not a physical process simulator.

## Workflow

1. Validate the input with [s1_input.md](docs/s1_input.md).
2. Run the aggregation with [s2_aggregate.md](docs/s2_aggregate.md).
3. Inspect and explain the result with [s3_validate.md](docs/s3_validate.md).

Public tool: `tools/summarize_rainfall.py`.
