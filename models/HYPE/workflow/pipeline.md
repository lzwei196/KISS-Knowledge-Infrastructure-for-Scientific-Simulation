# HYPE Pipeline Workflow

## Stage Dependencies

```
s1_subbasin_delineation ─┬─> s2_slc_classification ─┬─> s4_geodata_generation ──┐
                         │                           │                           │
                         ├─> s3_forcing_preparation ─│───────────────────────────>├─> s7_execution ─> s8_output_analysis
                         │                           │                           │
                         └─> s6_lake_reservoir_config│───────────────────────────>│
                                                     │                           │
                                                     └─> s5_parameter_setup ─────┘
```

## Execution Order

| Order | Stage | Tool(s) | Input | Output | Runtime |
|-------|-------|---------|-------|--------|---------|
| 1 | s1_subbasin_delineation | delineate_subbasins.py, validate_topology.py | Basin shapefile, outlet coords | subbasins.shp, maindown.csv | 1-3 min |
| 2a | s2_slc_classification | compute_slc_fractions.py, generate_geoclass.py | subbasins.shp, AVHRR, HWSD | GeoClass.txt, slc_fractions.csv | 2-5 min |
| 2b | s3_forcing_preparation | convert_forcing_to_hype.py | CMFD/MSWX, subbasins.shp | Pobs.txt, Tobs.txt, ForcKey.txt | 5-30 min |
| 2c | s6_lake_reservoir_config | setup_lake_data.py | GeoData.txt | LakeData.txt (optional) | <1 min |
| 3 | s4_geodata_generation | generate_geodata.py, validate_geodata.py | subbasins.shp, slc_fractions, maindown | GeoData.txt | <1 min |
| 4 | s5_parameter_setup | setup_parameters.py | GeoClass.txt, climate zone | par.txt | <1 min |
| 5 | s7_execution | configure_info.py, run_hype.py | All above | timeCOUT.txt, etc | 1-10 min |
| 6 | s8_output_analysis | parse_hype_output.py, plot_hype_results.py, compare_vic_hype.py | Result files | Plots, metrics | <1 min |

Stages 2a, 2b, 2c can run in parallel.

## Input File Checklist

Before running HYPE (s7_execution), verify all files exist:

```
run_directory/
  info.txt                  ← s7 configure_info.py
  modelfiles/
    GeoClass.txt            ← s2 generate_geoclass.py
    GeoData.txt             ← s4 generate_geodata.py
    par.txt                 ← s5 setup_parameters.py
    LakeData.txt            ← s6 setup_lake_data.py (optional)
  forcingdir/
    Pobs.txt                ← s3 convert_forcing_to_hype.py
    Tobs.txt                ← s3 convert_forcing_to_hype.py
    ForcKey.txt             ← s3 convert_forcing_to_hype.py
    Qobs.txt                ← observed data (optional, for evaluation)
  resultdir/                ← empty, HYPE writes here
  logdir/                   ← empty, HYPE writes here
```
