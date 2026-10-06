# s3 Watershed parameter file (.par)

## Purpose
Describe the watershed as a cascade of elements (planes, channels, ponds, ...) with geometry,
roughness and topology, in the order the engine must process them.

## Inputs
An existing parameter file to copy (ARS samples in `examples/ars_samples/`, or an AGWA export),
plus the changes you want.

## Outputs
A new parameter file; the original is never edited in place.

## Procedure
1. Inspect what the ENGINE will read: `tools/edit_kineros2_par.py list case.par`
   (it uses the engine's own lookup rules, so `PR = 2` shows PRI as '-').
2. Edit values token by token: `tools/edit_kineros2_par.py set case.par --out new.par --set 27:PRINT=2 --set PLANE:MANNING=0.05 --set 10:KSAT=0.4`
   - selector: element ID, element TYPE, GLOBAL or `*`; `TAG[:index]` for list/column positions
     (index 2 = second soil layer, or downstream section of a channel).
   - a tag that is absent is added as a new line before END.
3. Validate: `tools/edit_kineros2_par.py validate new.par --rain storm.pre` -- exit 2 on errors.
4. Put PRINT = 2 on the outlet (and any element you will compare with a gauge) to get a hydrograph table.

## Verification
- `validate` checks: GLOBAL first with UNITS and CLEN; unique IDs; every UPSTREAM/LATERAL id defined
  ABOVE its user; <=2 laterals; pervious elements have DIST, POR and a SAT source; LENGTH/SLOPE/roughness
  present; no line longer than 200 columns; no number split by '+'; every non-outlet element feeds a later one.
- Byte check: `diff old.par new.par` shows only the edited tokens (comments, CRLF kept).

## Traps
- Order matters: an element referenced before it is defined stops the engine ("lateral inflow not found",
  exit 0) (dt_kineros2_044).
- An element nobody references is computed but its water never reaches the outlet; the event summary
  "Outflow" is the LAST element only (dt_kineros2_042).
- `PR`/`PLOT` are not print flags; the engine asks for `PRI` (dt_kineros2_029).
- List values continue only on the same line (dt_kineros2_035); columns 201+ are ignored (dt_kineros2_045).
- Tags are matched by prefix: the first token starting with the requested letters wins.
- The CLEN warning ("numerical increment ... too large") is advisory; it appears in both official runs (dt_kineros2_037).

## Example
```
python3 tools/edit_kineros2_par.py set examples/ars_samples/EX1.PAR --out ex1_print.par --set 2:PRINT=2 --set PLANE:SAT=0.3
python3 tools/edit_kineros2_par.py validate ex1_print.par --rain examples/ars_samples/EX1.PRE
```
