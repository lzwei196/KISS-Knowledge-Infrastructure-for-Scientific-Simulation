# EPANET — foundation test case: "tutorial"

Authentic foundation case: the official **tutorial network** of the EPANET 2.2 User Manual
(Appendix C, "Example EPANET input file"). It is a small pumped system: 5 junctions,
1 reservoir, 1 tank, 6 pipes and 1 pump, run for 24 hours with hourly steps and
chlorine decay. `inputs/tutorial.inp` is the unmodified file from the EPANET git tree.

The same repo ships the official result next to it: `User_Manual/docs/tutorial.out`, the
"Excerpt from a EPANET report file" printed in the manual. It is kept here, unmodified, as
`reference/tutorial.out` and is the reference this case checks against.

| | |
|---|---|
| Engine | EPANET 2.2.0 (`runepanet` + `libepanet2.so`, built on this server) |
| Source | USEPA/EPANET2.2, commit 598ee6c, `User_Manual/docs/tutorial.inp` and `tutorial.out` |
| Licence | MIT (EPANET) |
| KI | `EPANET` |

## Run
```
python run_reference.py    # finds runepanet (--epanet-bin, $EPANET_BIN, PATH, server default); 0=PASS 2=FAIL 3=missing
```
It copies `inputs/` to a fresh temp dir, runs the engine through the KI's own
`tools/run_epanet.py`, turns the report into CSV with the KI's own
`tools/parse_epanet_output.py --rpt` (the same tool also reads the official excerpt),
checks `expected.json`, then deletes the temp dir. It takes a few seconds.

## Expected (recorded 2026-10-05)
- Finished normally: `run_epanet.py` exit 0 with `[SUCCESS]`, report ends with "Analysis ended", no errors.
- **All 83 numbers** in the official excerpt match our run: pump 7 energy row
  (745.97 kWh/Mgal, 51.35 kW average, 51.59 kW peak), node results at 0 h and 1 h,
  link results at 0 h. Tolerance 0.01 (one unit of the last printed digit); in fact the
  lines are text-identical.
- 12 key official values are also listed one by one in `expected.json`
  (e.g. node 2 head 893.19 ft, reservoir inflow -1049.81 gpm, pipe 5 flow -9.44 gpm,
  tank head at 1 h 855.99 ft, chlorine at node 3 at 1 h 0.99 mg/L).
- From our own run (the excerpt stops at 1 h): 25 hourly report periods, tank head at
  24 h 855.04 ft, chlorine at 24 h 0.53 mg/L (node 6) and 0.14 mg/L (tank 7). Two clean
  runs gave the same report (only date and path header lines differ).

## Known KI gaps (not fixed here)
- `tools/parse_epanet_output.py` cannot read the EPANET 2.2 binary `.out` file: it reads
  16-character IDs and a wrong prolog size, so `--summary` prints garbage (node ID "mg/L",
  pump 0, all zeros, "Reporting Periods 1057639384") but still exits 0. This case reads the
  text report with its `--rpt` mode instead, which works.
- The `--rpt` mode also writes the column-header row ("Demand, Head, ...") and page-header
  lines as data rows; `run_reference.py` drops rows that are not all numbers.
- The KI's own `find_binary()` only looks in paths relative to the live KI tree, so from
  this repo the binary is passed with `--binary`.
- The server `runepanet` has its RUNPATH set to the dissection-toolkit copy of
  `libepanet2.so`; `run_epanet.py` puts the disk1 solver dir first in `LD_LIBRARY_PATH`
  (both libraries are byte-identical).
