# dfnWorks foundation test case: graph_transport

## What it is
The official dfnWorks example `examples/graph_transport`. It builds a discrete fracture
network (DFN) and then runs flow and particle transport on the fracture graph:

- Domain 400 x 50 x 50 m, h = 1 m, only the largest connected cluster is kept.
- 3 families of elliptical fractures, radii from a truncated power law (10-20 m, alpha 1.8),
  target P32 = 0.25 m2/m3 each, constant permeability 2e-12 / 2e-12 / 3e-12 m2.
- Graph flow from the left face (2 MPa) to the right face (1 MPa).
- Graph particle tracking of 10,000 particles.

This example needs only DFNGen and pydfnworks. It does not need LaGriT, PFLOTRAN or FEHM,
which are not installed on this server. It is the smallest official example that runs
end to end with what is installed (the input is one 2.5 KB driver file; a run takes about 5 s).

## Source
- Repo: https://github.com/lanl/dfnWorks, commit `821d4761e6f468c62429256c3f8b7c82a4f06e49`
  (2026-03-09), file `examples/graph_transport/driver.py`.
- `inputs/driver.py` is the unmodified official file (taken with `git show HEAD:...`).
- Licence: LANL LA-CC-17-027, GNU LGPL v3 or later (see `LICENSE.md` in the dfnWorks repo).

## Engine
- DFNGen 2.3: `/home/server/knowledge-dissection-toolkit/auto_dissect/_work/dfnWorks/source/repo/DFNGen/DFNGen`
- pydfnworks 2.10.0 from the same repo, imported by
  `/mnt/disk1/Hydrocraft_server/python_env/bin/python` (Python 3.12).
- The helper programs DFNTrans, correct_volume and ConnectivityTest must also be built in the
  repo (pydfnworks checks them at start-up and would try to compile them otherwise).

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py
```
Options: `--dfngen-bin PATH` (or `$DFNGEN_BIN`), `--python PATH` (or `$DFNWORKS_PYTHON`),
`--record` (print values, no checks), `--keep` (keep the temp run dir).
Exit codes: 0 PASS, 2 checks failed, 3 engine or dependency missing (nothing is run).

What the script does:
1. Copies `inputs/driver.py` to a fresh temp dir and runs it there, unchanged.
2. Only the run environment is set: a private `HOME` with a `.dfnworksrc` that points at the
   repo (two levels above the DFNGen binary), and empty `LAGRIT_EXE`, `PFLOTRAN_EXE`,
   `FEHM_EXE`, `PETSC_DIR`, `PETSC_ARCH`. Without these empty variables pydfnworks stops with
   `KeyError: 'LAGRIT_EXE'` while printing its paths, even though this example never uses them.
   No input or code is changed.
3. Checks the return code and the model's own lines
   "Graph Particle Tracking Completed Successfully." and "All particles exited the network".
4. Reads `DFN_output.txt` (network counts, P32), `graph_flow.hdf5` (through the KI tool
   `tools/parse_dfnworks_output.py`) and `graph_partime.hdf5` (particle times), compares
   with `expected.json`, and deletes the temp dir.

## Expected results
No reference outputs ship with this example, so the values come from real runs on this server.
Three clean runs gave identical values. The network is repeatable because DFNGen uses the
pydfnworks default seed 1 (the driver does not change it), and each particle's random numbers
are seeded by its own particle number.

| check | expected |
|---|---|
| fractures accepted / final / isolated removed | 942 / 935 / 7 |
| intersections | 4385 |
| final P32 (m2/m3) | 0.750279 |
| graph edges | 50192 |
| mean edge flow rate (m3/s) | 1.05595e-10 |
| max edge velocity (m/s) | 7.21173e-05 |
| particles | 10000 |
| travel time min / median / mean / max (s) | 1.69165e8 / 3.44073e8 / 3.66977e8 / 2.64271e9 |
| mean path length (m) | 658.308 |
| mean Beta (s/m) | 1.38243e14 |

Counts must match exactly; floats use relative tolerance 1e-6.

## Known KI gaps
- The KI run tool `tools/run_dfnworks.py --mode graph` cannot drive this official case, so the
  official driver is run directly:
  - it has no way to set `domainSizeIncrease` ([5,5,5] here) or `disableFram` (True here), so
    it would build a different network;
  - it names the transport outputs `partime` / `frac_sequence` and then looks for a text file
    `partime`, but pydfnworks writes `partime.hdf5`, so its transport summary stays empty;
  - its `--seed` help says "0 = clock", but with 0 it does not set the seed, so the pydfnworks
    default seed 1 is used;
  - it does not set empty `LAGRIT_EXE` etc., so with the server's `.dfnworksrc` (empty LaGriT
    path) pydfnworks stops with `KeyError: 'LAGRIT_EXE'`.
- The KI parse tool `tools/parse_dfnworks_output.py --job_dir` reads `graph_flow.hdf5` well
  (used here), but it does not read `graph_partime.hdf5` ("No particle travel times found") and
  returns empty `params`. Particle times and network counts are read directly instead.
