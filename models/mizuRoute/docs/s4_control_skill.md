# Stage 4: Control File Reference

## Purpose
Generate the mizuRoute control file that specifies all input/output paths, variable names, routing method, and time settings.

## Format
Key-value pairs: `<variable_name>  value`. Lines starting with `!` are comments.

## Complete Variable Reference

### Paths
| Variable | Description | Example |
|----------|-------------|---------|
| `ancil_dir` | Directory for network/remap files | `/path/to/ancil/` |
| `input_dir` | Directory for runoff input files | `/path/to/input/` |
| `output_dir` | Output directory | `/path/to/output/` |
| `fname_ntopOld` | Network topology filename | `network_topology.nc` |
| `fname_qsim` | Runoff input filename | `runoff.nc` |
| `fname_output` | Output file prefix | `basin_name` |
| `fname_remap` | Remap weights filename | `remap_weights.nc` |

### Variable Name Mapping
| Control variable | Default (HydroCraft) | NHDPlus equivalent |
|-----------------|---------------------|-------------------|
| `vname_segid` | `seg_id` | `COMID` |
| `vname_tosegment` | `tosegment` | `toComid` |
| `vname_length` | `seg_length` | `LENGTHKM` |
| `vname_slope` | `seg_slope` | `SLOPE` |
| `vname_hruid` | `hru_id` | `COMID` |
| `vname_area` | `hru_area` | `AreaSqKM` |
| `vname_qsim` | `RUNOFF` | varies |
| `vname_time` | `time` | `time` |

### Routing Method
| Variable | Values | Default |
|----------|--------|---------|
| `route_opt` | 0=IRF, 1=KWT, 2=KWE, 3=MC, 4=DW | 0 |
| `doesBasinRoute` | 0 or 1 | 0 |
| `doesAccumRunoff` | 0 or 1 | 1 |

### Time
| Variable | Format | Example |
|----------|--------|---------|
| `sim_start` | YYYY-MM-DD HH:MM:SS | 2000-01-01 00:00:00 |
| `sim_end` | YYYY-MM-DD HH:MM:SS | 2010-12-31 00:00:00 |
| `dt` | seconds | 3600 |
| `calendar` | standard/noleap | standard |

## Common Pitfalls
- **Variable name mismatch (dt_m004)**: vname_* must exactly match NetCDF variable names
- **Path truncation (dt_m017)**: Keep all paths < 120 characters
- **Wrong units_qsim**: Must match actual runoff units in the NetCDF file
