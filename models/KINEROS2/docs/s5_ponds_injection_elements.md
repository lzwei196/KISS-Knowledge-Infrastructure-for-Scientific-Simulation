# s5 Ponds, flow injection and other elements

## Purpose
Represent detention ponds / stock tanks (storage-discharge routing with seepage) and outside inflow
(measured hydrographs, another model's output) inside the element cascade.

## Inputs
- Pond: rating table CSV `volume,discharge,surface` (cu m, cu m/s, sq m METRIC; cu ft, cu ft/s, sq ft ENGLISH),
  initial storage, optional seepage KS.
- Injection: hydrograph CSV `time_min,discharge[,conc per class]`, optional time offset.

## Outputs
A copied parameter file with the new block inserted at the right place and the downstream element
re-wired; for injection, an upper-case data file next to it (pass with `--extra-file`).

## Procedure
1. Pond spliced into an upstream link: `tools/add_kineros2_element.py --par wg11.par --out wg11_pond.par --type pond --id 900 --receives 23 --feeds 26 --rating rating.csv --print 1`
2. Injection into a channel: `tools/add_kineros2_element.py --par EX1.PAR --out ex1_inj.par --type inject --id 901 --feeds 2 --hydrograph inflow.csv`
   then `run_kineros2_engine.py --par ex1_inj.par ... --extra-file INJ901.DAT`.
3. PIPE (beta per ARS), URBAN, ADDER, DIVERTER, compound channels (OVERBANK block): edit by hand from
   the manual (src/doc/Input.pdf) and check with `edit_kineros2_par.py validate`.

## Verification
- Pond rules enforced before writing: 2-49 rows, volume starts at 0 and increases, discharge starts at 0
  and never decreases, surface > 0. Numbers are written in plain decimals.
- WG11 test: pond 900 (6-row illustrative rating) between channels 23 and 26 lowers the outlet peak from
  668.4 to 406.4 cfs and delays it from 64.7 to 85.1 min; 216,868 cu ft stays in the pond.
- EX1 test: a constant 0.1 m3/s injection for 200 min raises outflow from 705.97 to 1856.53 m3
  (+1150.6 m3 vs 1200 injected; the rest is channel storage at the end, 51.7 m3, and loss terms).

## Traps
- `1.6e+06` in a rating table is read as `1.6E` and `06` -> "volume entry (V) missing or invalid" (dt_kineros2_031).
- The FILE= name is upper-cased before opening: on Linux the file must exist in upper case (dt_kineros2_034).
- Injection time must start at 0; an OFFSET needs a zero first discharge.
- Pond rain (global PR = Y) and pond seepage (K) are off unless set.

## Example
```
printf 'volume,discharge,surface\n0,0,200000\n200000,0,200000\n400000,50,250000\n800000,200,300000\n1600000,600,400000\n3200000,1500,500000\n' > rating.csv
python3 tools/add_kineros2_element.py --par examples/ars_samples/wg11.par --out wg11_pond.par --type pond --id 900 --receives 23 --feeds 26 --rating rating.csv
```
