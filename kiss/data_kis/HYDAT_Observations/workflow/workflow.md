# Workflow

1. Use the ordinary acquisition workflow to obtain HYDAT. This reader performs no downloads.
2. Select an exact station and inclusive native date range in the approved plan.
3. Run structural/runtime preflight, then the declared reader with a fresh output directory.
4. Check actual station coordinates, source hash, native flags, duplicate and missing dates, and value status in the audit.
5. Resolve quality-policy and daily-time alignment before comparing with a scientific model. Preserve attribution to the data KI.
