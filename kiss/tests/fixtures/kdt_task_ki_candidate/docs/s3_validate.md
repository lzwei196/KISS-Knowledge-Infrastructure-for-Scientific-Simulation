# Stage 3 — validate output

The output fields are `month`, `total_precip_mm`, and `n_days`. Confirm months
are ordered, totals are non-negative, and the sum of monthly totals matches the
sum of valid input precipitation within CSV decimal precision. Record the tool
command, input path, output path, and any rejected row in the run report.
