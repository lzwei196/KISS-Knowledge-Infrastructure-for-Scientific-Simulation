# s9_water_quality

## Purpose

Enable HYPE nitrogen and phosphorus simulation and parse nutrient outputs. This stage uses HYPE's native NPC processes rather than an external nutrient coupling model.

## Inputs

- `info.txt` from s7 configuration
- `modelfiles/par.txt` from s5
- `modelfiles/GeoClass.txt` from s2
- Basin latitude/longitude and crop list for `CropData.txt`
- Region preset: `huai_river`, `midwest_us`, or `europe_temperate`
- HYPE `resultdir/` after running s7 with substances enabled

## Outputs

- `modelfiles/CropData.txt`
- Updated `info.txt` with `substance` and NPC output variables
- Updated `par.txt` with NPC parameters
- Nutrient output files such as `timeC1TN.txt` and `timeC1TP.txt`
- Parsed nutrient CSV

## Procedure

Generate crop management data:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s9_water_quality/generate_cropdata.py \
  --lat 32.4 \
  --lon 115.6 \
  --crops wheat,maize \
  --output outputs/hype_run/modelfiles/CropData.txt
```

Enable N/P in `info.txt` and add NPC parameters to `par.txt`:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s9_water_quality/configure_npc.py \
  --info_txt outputs/hype_run/info.txt \
  --par_txt outputs/hype_run/modelfiles/par.txt \
  --substances "N P" \
  --region huai_river \
  --geoclass outputs/hype_run/modelfiles/GeoClass.txt
```

Run s7 again, then parse nutrient outputs:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s9_water_quality/parse_npc_output.py \
  --result_dir outputs/hype_run/resultdir/ \
  --subbasin_id 1 \
  --basin_area_km2 11573 \
  --output_csv outputs/hype_run/nutrient_loads.csv
```

## Verification

- `info.txt` includes `substance N P` and output variables for computed main-flow concentrations (`c1IN`, `c1ON`, `c1TN`, `c1SP`, `c1PP`, `c1TP`).
- `par.txt` includes NPC parameters such as `fastn0`, `fastp0`, `denitwr`, `sedon`, `sedpp`, `freuc`, and crop/soil process parameters.
- `parse_npc_output.py` reads at least one `timeC1*.txt` file.
- Nutrient warmup is long enough for N/P pools to stabilize before interpreting concentrations.

## Traps

- `dt_s09`: nutrient concentrations are all zero because substances were enabled but `par.txt` lacks nutrient-specific parameters.
- `dt_r02`: added NPC land-use or soil-dependent parameters must still match `GeoClass.txt` maximum land-use and soil IDs.
- `dt_v02`: zero discharge from forcing or GeoClass defects invalidates nutrient concentrations; fix hydrology before interpreting NPC outputs.

## Example

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s9_water_quality/generate_cropdata.py \
  --lat 32.4 \
  --lon 115.6 \
  --crops wheat,maize \
  --output outputs/hype_run/modelfiles/CropData.txt

python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s9_water_quality/configure_npc.py \
  --info_txt outputs/hype_run/info.txt \
  --par_txt outputs/hype_run/modelfiles/par.txt \
  --substances "N P" \
  --region huai_river \
  --geoclass outputs/hype_run/modelfiles/GeoClass.txt

python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s9_water_quality/parse_npc_output.py \
  --result_dir outputs/hype_run/resultdir/ \
  --subbasin_id 1 \
  --basin_area_km2 11573 \
  --output_csv outputs/hype_run/nutrient_loads.csv
```
