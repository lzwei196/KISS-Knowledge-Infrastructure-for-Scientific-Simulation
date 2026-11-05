# s4 Erosion and sediment transport

## Purpose
Turn on KINEROS2's erosion/sediment routing: rain splash and hydraulic erosion on planes, erosion and
deposition in channels, transport of up to 5 particle classes through every element.

## Inputs
A parameter file that already runs for water; particle classes and per-element erosion parameters.

## Outputs
With the run's sediment flag on: event sediment yield (t/ha METRIC, short tons/acre ENGLISH) and yield
by particle class; per printed element the peak sediment discharge (kg/s or lb/s), a sediment balance
(in, deposited, soil loss, out) and, for PRINT = 2/3, sediment discharge per time step.

## Procedure
1. Check what is missing: `tools/configure_kineros2_sediment.py --check case.par`
2. Copy-first set-up (Smith method):
   `tools/configure_kineros2_sediment.py --par case.par --out case_sed.par --diams 0.005,0.05,0.25 --density 2.65,2.60,2.60 --temp 33 --plane-fract 0.2,0.6,0.2 --splash 50 --cohesion 0.5 --channel-fract 0,0.4,0.6 --channel-cohesion 0.01`
   (these are the ARS EX1 numbers -- a format example, not defaults for your site).
3. Run with sediment: `tools/run_kineros2_engine.py ... --sediment`.

## Verification
- `--check` exits 0 only when every Smith element has SPLASH (planes), COH, FRACT (sum 1 +/- 0.05,
  one value per class), the GLOBAL block has DIAMS and DENSITY of equal length, and the DIAMS
  magnitude fits the unit system.
- The official EX1 sample reproduces 5.172343 t/ha (0.25 mm 1.118723, 0.05 mm 1.175965, 0.005 mm 2.877656).
- WG11 + illustrative sediment tags: water results unchanged (outflow 0.292209 in), sediment 1.784 tons/ac.

## Traps
- DIAMS are INCHES and TEMP is deg F when UNITS = ENGLISH (dt_kineros2_041).
- FRACT is listed in DIAMS order; the engine re-orders classes internally by erodibility.
- PAV >= 1 makes the element non-eroding (SPLASH/COH then not needed); PAV > 1 stops the engine.
- A `KE` tag switches an element to RHEM, a `KR` tag to DWEPP; their parameters differ (dt_kineros2_043).
- Sediment tags with the run flag N are ignored silently; the flag Y without tags stops the engine (exit 0).

## Example
```
python3 tools/configure_kineros2_sediment.py --check examples/ars_samples/EX1.PAR      # sediment-ready
python3 tools/run_kineros2_engine.py --example ex1 --check --out-dir out/ex1            # 5.172343 t/ha
```
