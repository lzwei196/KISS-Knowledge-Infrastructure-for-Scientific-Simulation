# Stage S3 — Equilibrium spin-up

## Purpose
DayCent SOM pools (active, slow, passive) take centuries to converge to
their long-run steady state. The equilibrium run drives the model under a
representative climate cycle until SOM stops drifting. The `.bin` file
produced is then used as the starting state for historical and treatment
runs.

## Inputs
- `<eq>.sch` — schedule file with an `ACEQ` event that triggers adaptive
  termination
- `<site>.100`, `sitepar.in`, `soils.in`, `outfiles.in`
- `<weather>.wth` — repeating climate cycle (typically 30-100 years that
  the model recycles)
- DayCent binary `DDcentEVI_rev491`

## Outputs
- `eq.bin` — equilibrated state binary archive
- `eq.lis` — small text echo (when `-t` flag used)

## Procedure
```bash
cd run_dir
ln -sf $BIN_DIR/DDcentEVI_rev491 .
cp no_outfiles.in outfiles.in     # silence per-day outputs during spin-up
./DDcentEVI_rev491 -s wooster_eq -N eq
```

The schedule file embeds the equilibrium command:
```
+150 12/31 ACEQ A
```
where `+150` is the maximum block length, `12/31` is the calendar trigger,
`ACEQ` is the event keyword, and `A` is the option (adaptive). DayCent
checks SOM drift each block and terminates when within tolerance — typical
convergence in 750–1000 simulated years.

## Verification
- Return code 0 from `DDcentEVI_rev491`.
- `eq.bin` exists and is > 30 KB.
- Stdout contains `ACEQ` block convergence messages.
- If you extract `somsc` from `eq.bin` it should be in 5,000–15,000 g C / m²
  range for a temperate humid site.

## Traps
- **Non-converging ACEQ:** if the climate cycle is too short (< 30 years)
  or the soil profile is unrealistic, ACEQ may run to the schedule cap
  without converging. Symptom: `eq.bin` exists but `somsc` is still
  trending in the last block. Fix: extend the climate file.
- **Schedule starts before .wth file:** DayCent will silently recycle the
  climate file. Mostly harmless but distorts the calendar.
- **Wrong outfiles.in toggles:** during spin-up you do NOT want daily
  outputs. They produce GBs of data and slow the run dramatically. Always
  copy `no_outfiles.in` over `outfiles.in` before the equilibrium run.
- **`-N` overwrite:** `-N eq` overwrites any existing `eq.bin` without
  warning. Use `-n eq` if you need to preserve a prior file.

## Example
The Wooster example converges in ~750 years with a wallclock of 12 seconds
on a modern x86-64 host.
