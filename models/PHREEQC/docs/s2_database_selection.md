# Stage 2: Database Selection

## Purpose

Select the appropriate thermodynamic database for the geochemical problem. The database
determines which elements, species, and mineral phases are available, and which activity
coefficient model is used. Wrong database selection can cause silent errors where elements
are missing or activity models are inappropriate for the ionic strength.

## Inputs

| Input                 | Format  | Required | Source                  |
|-----------------------|---------|----------|------------------------|
| Element list          | Text    | Yes      | From Stage 1 (SOLUTION) |
| Ionic strength range  | mol/kgw | No       | Estimated from TDS      |
| Temperature range     | Celsius | No       | Field conditions        |
| Target minerals       | Text    | No       | Geological context      |

## Outputs

- Selected database file path
- Element coverage verification report
- Activity model compatibility assessment

## Procedure

1. **List all elements** required by the simulation (from SOLUTION blocks,
   EQUILIBRIUM_PHASES, EXCHANGE, SURFACE, KINETICS).

2. **Assess ionic strength**:
   - I < 0.7 mol/kgw: Use ion-association model (phreeqc.dat, wateq4f.dat, minteq.dat)
   - I > 0.7 mol/kgw: Use Pitzer model (pitzer.dat)
   - Nuclear waste: Use SIT model (sit.dat)

3. **Check element coverage** using this decision tree:

   ```
   Need trace elements (As, U, Se, Ni)?
     YES -> wateq4f.dat or minteq.dat
     NO  -> phreeqc.dat (default)

   High temperature (>100 C)?
     YES -> llnl.dat
     NO  -> standard databases

   Isotope tracking?
     YES -> iso.dat (supplementary)
     NO  -> not needed

   Brine/evaporite system (I > 1)?
     YES -> pitzer.dat (REQUIRED)
     NO  -> ion-association databases
   ```

4. **Verify element coverage**:
   ```bash
   # Check if all elements in input are in the database
   grep "^[A-Z]" database/phreeqc.dat | head -50
   # Or use the run_phreeqc.py preflight check
   ```

5. **Specify database** in the simulation:
   - Command line: `phreeqc input.pqi output.pqo database/wateq4f.dat`
   - In input file: `DATABASE /path/to/database.dat` (first line)

## Database Comparison

| Database      | Elements | Minerals | T Range  | I Range    | Activity Model |
|---------------|----------|----------|----------|------------|----------------|
| phreeqc.dat   | ~25      | ~80      | 0-100 C  | <0.7 mol   | Davies/B-dot   |
| wateq4f.dat   | ~40      | ~150     | 0-100 C  | <0.7 mol   | Davies/B-dot   |
| minteq.dat    | ~45      | ~200     | 25 C     | <0.5 mol   | Davies         |
| llnl.dat      | ~80      | ~400     | 0-300 C  | <3 mol     | B-dot          |
| pitzer.dat    | ~15      | ~40      | 25 C     | <6 mol     | Pitzer         |
| sit.dat       | ~30      | ~80      | 25 C     | <4 mol     | SIT            |

## Verification

1. Run a quick speciation and check that all elements are recognized
2. Verify no "Unknown element" or "Element not in database" errors
3. Compare speciation results between 2 databases as a sensitivity check
4. For high ionic strength, verify the Pitzer model is activated (check output header)

## Traps

| Trap | Description | Detection | Fix |
|------|-------------|-----------|-----|
| dt_004 | Element not in database | Fatal error on first run | Switch to wateq4f.dat or llnl.dat |
| dk_005 | Pitzer keywords with non-Pitzer DB | Silent: ion-association used instead | Use pitzer.dat exclusively for brines |
| dt_010 | llnl.dat with T extrapolation | Warnings about T range | Check analytic T expressions |

## Example

For a groundwater sample with As, Fe, Ca, Mg, Na, Cl, SO4, HCO3 at 20C and I~0.01:

```
# wateq4f.dat selected because:
# 1. Contains As (arsenic) - not in phreeqc.dat
# 2. Ionic strength < 0.7 (ion-association OK)
# 3. Temperature 20C (within range)

DATABASE database/wateq4f.dat

SOLUTION 1  Arsenic-contaminated groundwater
    temp    20.0
    pH      7.5
    pe      2.0
    units   mg/L
    Ca      80
    Mg      20
    Na      15
    Cl      30      charge
    S(6)    40      as SO4
    C(4)    200     as HCO3
    Fe      5.0
    As      0.050   # 50 ug/L - requires wateq4f.dat
END
```
