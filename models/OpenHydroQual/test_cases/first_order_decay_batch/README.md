# OpenHydroQual — foundation test case: "first_order_decay_batch"

Official foundation case: the **first order decay in a batch reactor** validation case
that ships with OpenHydroQual (`validation/first order decay in a batch reactor/`).
One closed reactor of 1 m^3 holds constituent A at 2 g/m^3; A decays at rate 0.7 * A per
day for 5 days. Upstream ships the exact answer (C = 2 exp(-0.7 t)) and a plot of the
model against it, so this case checks the engine against a known true answer.
`inputs/` are the unmodified files from the upstream git tree.

| | |
|---|---|
| Engine | OpenHydroQual `OHQLibTest` (command-line runner) + `libOHQLib.so.2`, built from git 58933b3 (2026-03-19), Qt 6.9 |
| Source | github.com/ArashMassoudieh/OpenHydroQual, `validation/first order decay in a batch reactor/` (commit 58933b3) |
| Licence | AGPL-3.0 (OpenHydroQual) |
| KI | `OpenHydroQual` (run with `tools/run_ohq.py`, output read with `tools/parse_output.py`) |

Files:
- `inputs/first_order_decay.ohq` — the model script (official, unchanged)
- `inputs/exact_solution.csv` — official exact solution, 51 points, t = 0..5 days (the .ohq also reads it as an observation)
- `reference/OHQ_vs_Exact_Batch_first_order.pdf` — official plot, model vs exact

## Run
```
python run_reference.py    # 0 = PASS, 2 = checks failed, 3 = engine/resources missing (not run)
```
Engine lookup: `--ohq-bin` -> `$OHQ_BIN` -> `which OHQLibTest` -> server default
(`.../_work/OpenHydroQual/source/repo/OHQLibTest/OHQLibTest`). Templates: `--resources` ->
`$OHQ_RESOURCES` -> `<bin>/../resources`. The binary must stay in its build tree, because it
reads `settings.json` from `<bin>/../../../resources/`.

It copies `inputs/` to a fresh temp dir, runs the engine through the KI's
`tools/run_ohq.py --fix-paths`, reads `output.txt` (about 1 MB, 5050 records) with the KI's
`tools/parse_output.py` and directly, checks `expected.json`, then deletes the temp dir.
The run takes about 0.1 s.

## The one change, and why it does not matter
The .ohq names its three template files with the developer's Windows paths
(`C:/Program Files (x86)/...`, `E:/Projects/...`). `run_ohq.py --fix-paths` writes
`first_order_decay_fixed.ohq` in the temp dir with only those three lines pointed to the
local `resources/` folder. The engine also falls back to its own template folder by file
name: running the untouched .ohq straight with the binary gave a byte-identical `output.txt`
(md5 06f5e715f07f924d88a48b56326803d8), so the change does not affect results.

## Expected (recorded 2026-10-05; two clean runs were byte-identical)
- finished normally: return code 0 and the engine line `Simulation finished!`
- against the **official exact solution** (51 points): largest gap 0.02426 g/m^3, largest
  relative gap 2.81 % (near t = 1, the same small lag the upstream plot shows). Check: every
  point within 5 % (upstream gives only the plot, no number tolerance; 5 % is our bound).
- 5050 output records, last time 5.049 days
- A concentration: first 1.99928, at t=1 0.985071 (exact 0.99317), t=2 0.484151 (exact
  0.49319), t=5 0.0615008 (exact 0.060395), lowest 0.0594625, mean 0.54325891
- volume stays exactly 1 m^3; A mass = concentration x volume at every record (gap 2e-05, from
  6-digit printing)

## Engine messages that are expected
The engine prints `Failed to parse configuration ... Line 1, Column 1` and three lines like
`Object 'Reactor (1)' has no property called 'inflow_timeseries'`. The .ohq was saved by an
older version and sets some empty inflow fields that today's templates have renamed. This
batch case has no inflow, so they do not change the result (it matches the exact solution).

## Why this case and not the others
Upstream git tracks 4 `Examples/` (Wet_pond 12 MB, Sewershed_Drywell 12 MB, Bioretention
3 MB, Water_Network 0.8 MB) and 2 `validation/` cases. The examples ship no reference output.
The validation cases ship an exact solution, which is the best reference. Of the two:
- **batch first-order decay** (this case) runs and matches the exact solution.
- **CSTR** does not reproduce today: its .ohq uses the old property names
  `inflow_timeseries` and `A:inflow_concentration`, which the current templates no longer
  have (now `time_variable_inflow` / `time_variable_inflow_concentration`). The engine
  ignores them, so no water or A flows in and A stays 0, while the exact answer rises to
  about 0.29 g/m^3. This is a stale upstream file, not a KI fault; it is not packaged.
(Water_Network also ran through `run_ohq.py` in 0.5 s, but it has no reference output.)

## KI gaps (status 2026-10-06)

No KI tool fix for OpenHydroQual has landed in this checkout since the case was made (last OpenHydroQual commit `920a698`), so every item below is still open.

- **Still open:** `tools/run_ohq.py` exits 0 even when the model fails; the failure only shows as
  `"status": "error"` in its JSON. `run_reference.py` reads that status.
- **Still open:** `run_ohq.py --fix-paths` changes only the `loadtemplate`/`addtemplate` lines. It cannot
  update old property names in older .ohq files (the CSTR case above).
