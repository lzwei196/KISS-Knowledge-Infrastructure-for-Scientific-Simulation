# Workflow

1. Acquire the raw yearly files through the normal data workflow. The reader makes no network requests.
2. Review the exact station and inclusive native date range; use a new output directory.
3. Run structural/runtime preflight and the declared reader.
4. Read the audit and optional excluded-record file; resolve gaps, coordinate changes, unknown timezone and sensor-depth evidence.
5. Obtain weather and site inputs separately. Match model temperature to observation depth and timing before comparison. Reader completion is data preparation only.
