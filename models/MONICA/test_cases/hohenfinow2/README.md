# MONICA test case: hohenfinow2 (official Hohenfinow2 example)

## What it is
The example that ships with MONICA itself: a 7-year crop rotation (1991-1997) on a sandy
loam field at Hohenfinow, Brandenburg, Germany (lat 52.81). Crops in order: winter rye,
silage maize, potato, winter wheat, winter barley, spring barley, winter rape. Daily
weather comes from the shipped `climate.csv`. MONICA writes one CSV (`sim-out.csv`) with
six sections: daily, monthly, yearly, run, crop and a yearly 31 March snapshot.

## Source
- Repo: https://github.com/zalf-rpm/monica, folder `installer/Hohenfinow2`
  (git commit f821718, 2026-03-17, "bump repo to latest version").
- `inputs/sim.json`, `crop.json`, `site.json`, `climate.csv` are the unmodified files
  taken with `git show HEAD:installer/Hohenfinow2/<file>` (all four are tracked upstream).
- The run also needs the MONICA parameter library (crop, residue and fertiliser files)
  from https://github.com/zalf-rpm/monica-parameters (git fb0f478, 2023-10-27). It is
  not copied here; it is found through `MONICA_PARAMETERS` (sim.json uses
  `"include-file-base-path": "${MONICA_PARAMETERS}/"`).
- Licence: MPL-2.0 (MONICA and monica-parameters), (c) ZALF.

## Engine
`monica-run` version 3.6.53.0, server build at
`/mnt/disk1/Hydrocraft_server/models/MONICA/bin/monica-run`. One run takes about 0.2 s.

## How to run
```
python run_reference.py [--monica-bin PATH] [--monica-parameters DIR]
```
Binary lookup: `--monica-bin` -> `$MONICA_BIN` -> `which monica-run` -> server default.
Parameter lookup: `--monica-parameters` -> `$MONICA_PARAMETERS` -> server default.
The script copies the four inputs to a fresh temp dir, runs them through the KI's own
`tools/run_monica.py`, reads `sim-out.csv`, checks `expected.json`, then deletes the temp
dir. Exit 0 = PASS, 2 = checks failed, 3 = engine or parameter library missing.

## Expected results
No usable official reference output ships with this example. The folder does hold
tracked `out.csv` and `min-out-monica.csv`, but their columns do not match any of the
current `sim*.json` files, so they come from an older setup and are not used.
The expected values were recorded from real runs on 2026-10-05. Three clean runs (two
through the KI run tool, one with `monica-run` directly) gave byte-identical output
(sha256 `33ed0613...829c`), so the model is deterministic here.

Main values:
| check | value |
|---|---|
| daily rows (1991-01-01 .. 1997-12-31) | 2557 |
| monthly / yearly rows | 84 / 7 |
| crops in the crop section | 7 |
| rain total, run section = sum of daily rain | 3502.5 mm |
| yield winter rye 1992 / silage maize 1993 / potato 1994 | 3356.9 / 1145.9 / 9098.6 kgDM/ha |
| yield winter wheat 1995 / spring barley 1996 | 8446.0 / 6676.9 kgDM/ha |
| sum of all 7 crop yields | 28724.3 kgDM/ha |
| largest daily LAI / above-ground biomass | 15.2314 / 20595.8 kgDM/ha |
| N leaching / recharge, sum of yearly rows | 415.415 kgN/ha / 863.32 mm |

Winter barley (harvested 1996-04-13) and winter rape (sown 1997-04-04, harvested
1997-07-08) give a yield of 0 with the dates set in the official `crop.json`; this is
what the official example produces and is recorded as is.
"Finished normally" = run tool return code 0 with status "success" and the output file
written (`monica-run` prints no success line; it is silent when it works).

## Known KI gaps
- `tools/run_monica.py` passes `--output` to `monica-run -o`. With a bare file name
  (its default `out.csv`) `monica-run` prints `Error failed to create path: ''.` on
  stderr, yet still writes the file and exits 0; the run tool then lists this as a
  warning. With a full path the message is gone. `run_reference.py` passes a full path;
  the output is byte-identical either way.
- `tools/parse_monica_output.py` stacks all six output sections into one table, so its
  summary adds things up across sections (for this case it reports rain 10507.5 mm
  instead of 3502.5 and 443 "harvests" instead of 7). `run_reference.py` therefore reads
  `sim-out.csv` directly, section by section.
- The KI tools only make `climate.csv` and site soil; crop rotation, management and
  `sim.json` come from a template, so this case uses the official files as they are.
