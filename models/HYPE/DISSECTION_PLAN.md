# HYPE Dissection Plan

## Model: HYPE v5.35.0 (HYdrological Predictions for the Environment)
## Status: Binary validated, knowledge infrastructure complete

## Classification (from PREFLIGHT.md)
- [x] Has Fortran code -> Fortran traps apply
- [x] Reads fixed-width text files -> Tab-separated, column alignment matters
- [x] Will be coupled with other models -> VIC coupling
- [x] Has physical units -> mm/day, m3/s, degrees C
- [x] Uses spatial data -> Subbasin shapefiles, lat/lon
- [x] Has flow routing / drainage network -> MAINDOWN topology
- [ ] Is a crop/ecosystem model
- [ ] Runs on Linux but built for Windows -> Pure Linux build
- [ ] Is a lake/reservoir model -> Has lake support, but not primary purpose
- [ ] Needs long spinup -> 1 year warmup sufficient

## Installation
- **Source**: SourceForge `release_hype_5_35_0/hype_3_35_0_src.tgz` (812 KB)
- **Compile**: `make comp=gfortran` (38 Fortran 90 files, 93,622 lines, ~60s)
- **Binary**: `/mnt/disk1/Hydrocraft_server/model/hype/hype` (3.1 MB)
- **Dependencies**: None (pure Fortran 90, no NetCDF, no MPI)
- **Demo**: 3-subbasin test case at `/mnt/disk1/Hydrocraft_server/model/hype/demo/`

## Validation Steps Completed
1. [x] Downloaded source from SourceForge (v5.35.0, latest as of 2026-02)
2. [x] Compiled with gfortran 13.3.0 (warnings only, no errors)
3. [x] Created 3-subbasin demo dataset with synthetic forcing
4. [x] Debugged info.txt format (trailing slash requirement, crit format)
5. [x] Debugged GeoClass.txt format (SLC ID column, numlayers)
6. [x] Debugged par.txt format (land-use vs soil-dependent value counts)
7. [x] Ran HYPE successfully (exit code 0, output files generated)
8. [x] Validated output parsing tool (parse_hype_output.py)
9. [x] Validated topology checker (validate_topology.py)
10. [x] Validated GeoData checker (validate_geodata.py)

## Key Discoveries (Triplets)
- **dt_r01**: Trailing slash on directory argument is REQUIRED (Fortran string concat)
- **dt_r02**: par.txt value count must match max(landuse/soil IDs), not number of SLC classes
- **dt_r03**: GeoClass.txt needs explicit SLC ID as first column
- **dt_s01**: SLC fractions not summing to 1.0 is a SILENT ERROR
- **dt_s02**: AREA in wrong units (km2 vs m2) produces plausible but wrong results
- **dt_s07**: Tab vs space separators — HYPE Fortran parser requires actual tabs

## Pipeline (8 stages, 16 tools)
See knowledge_infrastructure.yaml for full manifest.

## Pending Work
- Full HydroCraft data validation (real basin with CMFD/MSWX forcing)
- Nutrient simulation testing (N/P with substance flags)
- Lake regulation testing (LakeData.txt + DamData.txt)
- Calibration integration (DDS optimizer)
- World-Wide HYPE parameter extraction for real basins
