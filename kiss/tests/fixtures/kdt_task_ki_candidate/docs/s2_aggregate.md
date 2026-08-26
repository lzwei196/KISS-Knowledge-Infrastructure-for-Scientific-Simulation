# Stage 2 — aggregate

Run `python3 tools/summarize_rainfall.py --input INPUT.csv --output OUTPUT.csv`.
The command groups valid rows by calendar month, sums precipitation without a
unit conversion, and counts contributing days. A non-zero exit means no output
should be trusted. Preserve the original input alongside the result.
