# s7 AED2 Config

## Purpose

Generate optional AED2 water-quality configuration and add nutrient/WQ loading to GLM inflow files. This stage is optional for thermal-only GLM runs and must be handled conservatively for the current v3.3.3 binary.

## Inputs

- Existing inflow CSV from s3.
- AED2 module choices and optional phytoplankton groups.
- Trophic state or observed nutrient concentrations.
- Tools:
  - `tools/s7_aed_config/generate_aed_config.py`
  - `tools/s7_aed_config/configure_inflow_wq.py`

## Outputs

- `aed2.nml` from `generate_aed_config.py`.
- WQ-augmented inflow CSV, usually `bcs/inflow_1_wq.csv`.
- JSON note from `configure_inflow_wq.py` showing the required `inflow_varnum` and `inflow_vars` values for `glm3.nml`.

## Procedure

1. For nutrient/oxygen work on this binary, prefer the simplified core-nutrient module set documented in `SKILL.md` and `diagnostics/triplets.yaml`:

```bash
python tools/s7_aed_config/generate_aed_config.py \
  --modules oxygen,nitrogen,phosphorus,organic_matter,totals \
  --output aed2.nml
```

2. Add nutrient and oxygen loading to an existing inflow file:

```bash
python tools/s7_aed_config/configure_inflow_wq.py \
  --inflow_csv bcs/inflow_1.csv \
  --trophic mesotrophic \
  --seasonal \
  --output bcs/inflow_1_wq.csv
```

3. If intentionally testing phytoplankton despite the known v3.3.3 risk, generate dependencies and then verify finite WQ output immediately after s8:

```bash
python tools/s7_aed_config/generate_aed_config.py \
  --modules oxygen,nitrogen,phosphorus,organic_matter,silica,phytoplankton,sedflux,totals \
  --phyto_groups diatom,green,cyano \
  --output aed2.nml
```

4. Manually update `glm3.nml` after s6: add `&wq_setup`, set `wq_lib='aed2'`, set `wq_nml_file='aed2.nml'`, update `inflow_varnum`/`inflow_vars`, and add WQ names/initial values in `&init_profiles`.

## Verification

- `aed2.nml` exists and includes only intended modules.
- WQ inflow CSV keeps `FLOW,TEMP,SALT` and adds AED2 variable columns such as `NIT_nit`, `NIT_amm`, `PHS_frp`, `OGM_doc`, and `OXY_oxy`.
- The `glm_nml_inflow_config` printed by `configure_inflow_wq.py` is copied into `glm3.nml` before s8.
- After s8, first WQ output rows are finite; do not trust runs with `-nan` WQ columns or all-fill `output.nc` WQ variables.

## Traps

- `dt_028`: phytoplankton requires oxygen, nitrogen, phosphorus, organic matter, and silica for diatoms.
- `dt_029`: inflow without nutrient columns gives zero external loading and unrealistic oligotrophic results.
- `dt_030`: WQ initial values must equal `num_wq_vars * num_depths`.
- `dt_032`: phytoplankton/silica/noncohesive can silently poison all AED2 state variables on this v3.3.3 binary.
- `dt_033`: `generate_glm_nml.py` does not fully wire AED2; manual namelist edits are required.
- `dt_034`: use careful output extraction for depth-resolved WQ; bulk reads of large padded NetCDF variables can segfault.

## Example

```bash
python tools/s7_aed_config/generate_aed_config.py \
  --modules oxygen,nitrogen,phosphorus,organic_matter,totals \
  --output aed2.nml
python tools/s7_aed_config/configure_inflow_wq.py \
  --inflow_csv bcs/inflow_1.csv \
  --trophic eutrophic \
  --output bcs/inflow_1_wq.csv
```
