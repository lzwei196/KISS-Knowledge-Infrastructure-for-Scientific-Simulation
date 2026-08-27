# Stage 3: Model Configuration

## Purpose
Assemble the forcing, parameter file, basin area, run mode, and calibration window before invoking `tools/run_velma.py`. This is a manual stage in `SKILL.md`; it has no separate converter script.

## Inputs
- Forcing JSON produced by `docs/s1_forcing_preparation.md`.
- Parameter JSON produced by `docs/s2_soil_parameter_setup.md`.
- Basin area in square kilometers for the `mm/d` to `m3/s` conversion.
- Optional observed discharge CSV/TSV for calibration.
- Optional calibration dates, usually starting after at least one spin-up year.
- References: `SKILL.md` Sections 3, 7, 9, 10, and 12; `dag.yaml`; `docs/validation_convention.yaml`; `diagnostics/triplets.yaml`.

## Outputs
- A concrete `tools/run_velma.py` command in either `simulate` or `calibrate` mode.
- A consistent set of paths and units for execution and later parsing.

## Procedure
Confirm the runner options:

```bash
python tools/run_velma.py --help
```

For simulation, configure these required arguments:

```bash
python tools/run_velma.py \
  --mode simulate \
  --forcing forcing.json \
  --params params.json \
  --basin-area-km2 121330 \
  --output simulation.json
```

For calibration, include observations and the calibration window:

```bash
python tools/run_velma.py \
  --mode calibrate \
  --forcing forcing.json \
  --params params.json \
  --observed /path/to/observed_Q.csv \
  --basin-area-km2 121330 \
  --cal-start 1981-01-01 \
  --cal-end 1985-12-31 \
  --maxiter 80 \
  --popsize 20 \
  --output calibrated.json
```

Use `dag.yaml` to keep scope clear: this KI is the Python lumped daily four-layer engine, not the EPA Java spatial VELMA with carbon/nitrogen modules.

## Verification
- The configured command points to `tools/run_velma.py`, not a substitute model.
- The basin area is in `km2`.
- Simulation mode includes `--params`.
- Calibration mode includes `--observed` and excludes the spin-up year from `--cal-start`.
- Forcing fields match `prec_mm_d`, `temp_K`, and `srad_Wm2`.
- Parameter JSON contains all 14 process parameters listed in `SKILL.md`.

## Traps
- `dt_velma_007`: basin area unit confusion, especially hectares passed as square kilometers.
- `dt_velma_010`: calibration window includes spin-up, producing high calibration scores and poor validation.
- `dt_velma_011`: Java VELMA XML paths are irrelevant to this Python runner unless using the original Java package separately.
- `dt_velma_018`: missing Python dependencies such as pandas, scipy, xarray, geopandas, or matplotlib.
- `dt_velma_021`: first-year soil-water transient contaminates metrics if not excluded.

## Example
The KI validation setup in `SKILL.md` uses Bengbu station, Huai River Basin, area `121330 km2`, forcing period `1980-1990`, calibration `1981-01-01` to `1985-12-31`, and spin-up year `1980`.
