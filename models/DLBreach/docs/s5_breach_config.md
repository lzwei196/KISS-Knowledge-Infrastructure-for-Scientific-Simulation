# S5 Breach Config

## Purpose

Generate breach-mode, sediment, roughness, pilot breach, and initial water-level cards, then assemble all stage outputs into the single DLBreach `casename.txt` input file. This is the stage that should add the required `Downstream_Channel_Flow_Out` card through `assemble_input_file.py`.

## Inputs

- S2 `geometry_json` from `create_dam_geometry.py`.
- S3 `reservoir_json` from `create_reservoir_curve.py`.
- S4 `inflow_json` from `convert_cama_to_inflow.py`.
- Breach mode, sediment type, d50, internal friction as `tan(phi)`, porosity fraction, Manning's n or defaults, and initial upstream/downstream WSL relative to embankment base.
- Time control: `--time_step` in seconds and `--sim_period` as `start_sec, end_sec`.

## Outputs

- `breach.json` containing `parameter_cards`.
- `WORKDIR/CASE.txt`, the complete DLBreach card file.
- Optional assembly metadata JSON with required and recommended card checks.

## Procedure

Create breach parameter cards:

```bash
python3 tools/s5_breach_config/set_breach_parameters.py \
  --breach_mode 1 \
  --overtopping_mode 1 \
  --sediment_type 1 \
  --sediment_diameter 0.001 \
  --internal_friction 0.577 \
  --cohesion_pa 0 \
  --upstream_wsl 31 \
  --downstream_wsl 0.01 \
  --output outputs/demo/breach.json
```

Assemble the final input file:

```bash
python3 tools/s5_breach_config/assemble_input_file.py \
  --casename demo \
  --output_dir outputs/demo \
  --time_step 1 \
  --sim_period "0, 86400" \
  --geometry_json outputs/demo/geometry.json \
  --reservoir_json outputs/demo/reservoir.json \
  --inflow_json outputs/demo/inflow.json \
  --breach_json outputs/demo/breach.json \
  --output outputs/demo/assemble.json
```

Use `docs/format_spec.yaml` for card units and `SKILL.md` for recommended parameter values.

## Verification

- `breach.json` has `status: success`.
- Assembly returns `status: success`, not `incomplete`.
- `required_missing` is empty.
- `outputs/demo/demo.txt` contains `Downstream_Channel_Flow_Out`.
- `Time_Step` and `Simulation_Period` are seconds, while inflow table times remain hours.

## Traps

- `dt_006`: required cards missing. Re-run S2, S3, S4, and `set_breach_parameters.py`, then assemble again.
- `dt_005`: malformed multiline card block. Do not hand-edit comments or blank lines into reservoir or inflow data blocks.
- `dt_010`: water levels are meters above embankment base, not absolute elevations.
- `dt_012`: `Sediment_Internal_Friction` is `tan(phi)`, not degrees.
- `dt_013`: `Sediment_Porosity` is a fraction such as `0.35`, not `35`.
- `dt_014`: cohesive `kd` is in cm3/N-s in the DLBreach card convention.
- `dt_020`: piping breach pipe elevation must be below upstream WSL.
- `dt_021`: overtopping will not initiate unless upstream WSL exceeds the crest or inflow raises it above crest during the run.

## Example

```bash
cd KISSPATH_KI_ROOT/DLBreach/knowledge_infrastructure
python3 tools/s5_breach_config/assemble_input_file.py \
  --casename example_case \
  --output_dir outputs/example_case \
  --time_step 1 \
  --sim_period "0, 86400" \
  --geometry_json outputs/example_case/geometry.json \
  --reservoir_json outputs/example_case/reservoir.json \
  --inflow_json outputs/example_case/inflow.json \
  --breach_json outputs/example_case/breach.json \
  --ds_channel_width 50 \
  --ds_channel_slope 0.005 \
  --ds_channel_manning 0.03 \
  --output outputs/example_case/assemble.json
```

