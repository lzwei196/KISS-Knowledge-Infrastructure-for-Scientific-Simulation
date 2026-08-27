# s1_vic_routing_input

Prepare VIC or VIC-like runoff output for the Lohmann routing binary.

## Inputs

- Raw VIC flux text files from the basin run directory.
- The VIC global parameter file that declares `OUTVAR` ordering.
- `preprocess_vic_for_routing.py` in the KI root.

## Required Contract

The routing binary reads per-cell daily ASCII files with exactly seven columns:

`YEAR MONTH DAY PREC EVAP RUNOFF BASEFLOW`

There is no header. `RUNOFF` and `BASEFLOW` are in `mm/day`. The Fortran routing code reads column 6 and column 7 for the routed inflow. Raw VIC 5.x output with many `OUTVAR` columns must not be passed directly to routing.

## Procedure

Run `preprocess_vic_for_routing.py` with the VIC result directory, VIC global parameter file, and an output directory such as `vic_in`.

After preprocessing, verify the files before routing:

```bash
awk 'NF!=7{print FILENAME":"FNR":"NF; exit 1}' vic_in/fluxes_*
```

The output filename prefix must match the prefix configured in `rout_global.txt`; this KI uses the `fluxes_` convention in the preprocessing and routing notes.

## Failure Modes

- `dt_005`: raw VIC output columns are read as runoff/baseflow, producing huge or negative discharge.
- `dt_007`: coordinate precision or grid-origin mismatch makes routing print `NOT FOUND, INSERTING ZEROS`.
- `dt_017`: the first year/month in the preprocessed files does not match the date block in `rout_global.txt`.
