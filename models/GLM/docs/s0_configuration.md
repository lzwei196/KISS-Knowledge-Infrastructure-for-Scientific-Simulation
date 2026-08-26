# s0 Configuration

## Purpose

Choose a valid GLM lake/reservoir target, simulation period, forcing source, timezone, coupling mode, and whether AED2 water quality is enabled before any generated files are made. This stage is the applicability gate for this KI: GLM is a 1-D lake/reservoir column model, not a catchment runoff or river-discharge model.

## Inputs

- User intent: lake/reservoir name or coordinates, variables to simulate/validate, period, and requested coupling.
- `SKILL.md` pipeline, applicability notes, and Quick Start.
- `dag.yaml` boundary, inputs, outputs, and observability definitions.
- `docs/format_spec.yaml` for required GLM variables and native units.
- `diagnostics/triplets.yaml` for known failure IDs.

## Outputs

- A selected lake/reservoir target with `lat`, `lon`, `start_date`, `end_date`, and `timezone`.
- A forcing choice for s2: `nasa_power`, on-disk CMFD/MSWX via `--forcing_dir`, or VIC forcing via `--vic_forcing_dir`.
- A decision on inflow/outflow handling for s3 and s4.
- Optional AED2 choice for s7, with a clear decision to avoid or include phytoplankton/silica.

## Procedure

1. Read the KI entrypoint and DAG before running tools:

```bash
sed -n '1,220p' SKILL.md
sed -n '1,260p' dag.yaml
sed -n '1,220p' docs/format_spec.yaml
```

2. Confirm the model binary and local dependencies before preparing a run:

```bash
python preflight_check.py
```

3. If the target comes from coordinates or a lake name, plan s1 lookup against HydroLAKES:

```bash
python tools/s1_lake_identification/lookup_hydrolakes.py \
  --lat 46.0 --lon -89.7 --radius_km 10 --output lake_lookup.json
```

4. If the requested variable is not an in-lake GLM output in `dag.yaml` (`temp`, `surface_temp`, `bottom_temp`, `lake_level`, `ice_thickness`, AED2 WQ variables, etc.), reject GLM for that request rather than forcing a run.

## Verification

- `python preflight_check.py` completes or reports a real missing binary/data dependency.
- The request is for a lake/reservoir, not a river gauge or basin discharge.
- The requested validation variable appears in `dag.yaml` outputs and has an observation shape compatible with the available data.
- The period and timezone will be used consistently by s2 meteorology, s3 inflow, and s6 namelist.

## Traps

- `dt_031`: discharge/streamflow requests at a creek or river gauge are a domain mismatch; use a routing model instead of GLM.
- `dt_016`: met forcing and inflow timestamps can be offset by timezone mismatches.
- `dt_017`: CaMa grid cells must correspond to the actual lake inlet/outlet, not just a nearby grid point.
- `dt_032`: with this v3.3.3 binary, phytoplankton/silica/noncohesive AED2 configurations can silently NaN the whole WQ state.

## Example

For a lake outside local CMFD/MSWX coverage, choose NASA POWER forcing in s2, constant or CaMa/VIC-derived inflow in s3, balance or scheduled outflow in s4, then generate `glm3.nml` and run the actual binary:

```bash
python preflight_check.py
python tools/s2_met_forcing/convert_met_to_glm.py \
  --forcing_source nasa_power --lat 34.1932 --lon -86.8052 \
  --start_date 2014-01-01 --end_date 2020-12-31 \
  --output bcs/met.csv
```
