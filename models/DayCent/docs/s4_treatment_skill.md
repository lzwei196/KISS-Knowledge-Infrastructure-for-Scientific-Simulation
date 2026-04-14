# Stage S4 — Base history and treatment runs

## Purpose
Once the equilibrium state is built, run two more stages:
1. **Base history** — historical management without the experimental treatment
   (the "control" baseline, often 1900–1961 for Midwestern U.S. sites).
2. **Treatment** — the experimental scenario whose results you actually want
   (e.g. Wooster Corn-Soy no-till, 1962-present).

Both stages chain off the previous binary via the `-e` flag.

## Inputs
- `eq.bin` from stage S3
- `<base>.sch` and `<treat>.sch` schedule files
- `<weather>.wth` covering the historical and treatment periods
- All site files unchanged from stage S1

## Outputs
- `base.bin` — state at the end of the base history
- `treat.bin` (or named like `cb_nt.bin`) — state at the end of the treatment

## Procedure
```bash
# Base history extends the equilibrium binary
./DDcentEVI_rev491 -s wooster_base -e eq -N base

# Treatment extends the base history
cp few_outfiles.in outfiles.in
./DDcentEVI_rev491 -s wooster_cb_nt_blk1 -e base -N cb_nt
```

The `-e <bin>` flag tells DayCent to read the prior binary as initial state
and *extend* it; `-i <bin>` would reset internal counters. Use `-e` to chain
treatment runs that share state, `-i` only when starting fresh from a stored
spin-up state.

## Verification
- Return code 0 for each step.
- Each `.bin` file exists, > 30 KB, and is newer than its predecessor.
- `summary.out` (if enabled in `outfiles.in`) shows continuous time from the
  start of base history through the end of treatment.
- `harvest.csv` has one row per `HARV` event in the schedule.

## Traps
- **Schedule mismatch:** if `<base>.sch` starts at year 1900 and `<treat>.sch`
  starts at year 1900, the treatment overwrites the base period. Treatment
  schedule must start at the year base history ended.
- **Climate file mismatch:** the `Weather choice` line in the schedule must
  point to a file that covers the schedule years. DayCent recycles silently.
- **`outfiles.in` not switched back:** if you forget to `cp few_outfiles.in
  outfiles.in` before the treatment, you get no daily outputs. The model
  succeeds but you have nothing to extract.
- **Different `<site>.100` between runs:** all three runs (eq, base, treat)
  must use the same site file or SOM will jump discontinuously.

## Example
```
$ ls -la *.bin
-rw-r--r-- 1 user user  37620 Apr 14 13:35 eq.bin
-rw-r--r-- 1 user user  41330 Apr 14 13:36 base.bin
-rw-r--r-- 1 user user  43900 Apr 14 13:38 cb_nt.bin
```
