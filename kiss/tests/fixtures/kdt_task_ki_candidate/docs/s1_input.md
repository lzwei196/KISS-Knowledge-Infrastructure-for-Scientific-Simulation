# Stage 1 — validate input

Input is a UTF-8 CSV with exactly the fields `date` and `precip_mm`. Dates use
ISO `YYYY-MM-DD`; precipitation is a non-negative millimetre value. Check the
header and at least one record before running. A malformed date, missing field,
or negative value is a hard failure and must be corrected in the source data.
