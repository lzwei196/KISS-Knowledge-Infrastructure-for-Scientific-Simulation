# SNOWPACK — Workflow

Auto-generated pipeline with 9 stages.

## Pipeline Stages

### Stage 0: Configuration (`s0_config`)

- **Description**: Set basin, period, resolution, paths
- **Dependencies**: none

### Stage 1: Domain / Grid Setup (`s1_domain`)

- **Description**: Define computational grid or HRUs from DEM and basin shapefile
- **Dependencies**: none
- **From documentation**:
  - Modify the `io_files/<model>.ini` to have DEMFILE and SOURCE_DEM point to the DEM, and METEOPATH and GRID2DPATH to the paths containing NetCDF files with the parameters
  - Make sure the `meteoio_timeseries` executable is available in `./create_smet_from_netcdf/` folder (either make a copy, or a soft-link). Test if the executable executes (`./meteoio_timeseries`). Check for example if modules need to be loaded (and make sure they are loaded in the sbatch script too!).
  - Postprocessing: Concatenate and zip individual yearly atmospheric forcing files into a continous time series located at `output/smet_forcing.zip`. `postprocess.sh` requires the atmospheric model as an argument, for example:

### Stage 2: Soil Parameters (`s2_soil`)

- **Description**: Derive soil hydraulic properties from HWSD or SoilGrids
- **Dependencies**: s1_domain
- **From documentation**:
  - Modify the `io_files/<model>.ini` to have DEMFILE and SOURCE_DEM point to the DEM, and METEOPATH and GRID2DPATH to the paths containing NetCDF files with the parameters

### Stage 3: Vegetation / Land Cover (`s3_vegetation`)

- **Description**: Classify land cover from AVHRR into model vegetation classes
- **Dependencies**: s1_domain
- **From documentation**:
  - Modify the `io_files/<model>.ini` to have DEMFILE and SOURCE_DEM point to the DEM, and METEOPATH and GRID2DPATH to the paths containing NetCDF files with the parameters
  - Make sure the `meteoio_timeseries` executable is available in `./create_smet_from_netcdf/` folder (either make a copy, or a soft-link). Test if the executable executes (`./meteoio_timeseries`). Check for example if modules need to be loaded (and make sure they are loaded in the sbatch script too!).
  - Postprocessing: Concatenate and zip individual yearly atmospheric forcing files into a continous time series located at `output/smet_forcing.zip`. `postprocess.sh` requires the atmospheric model as an argument, for example:

### Stage 4: Meteorological Forcing (`s4_forcing`)

- **Description**: Convert CMFD/MSWX/NASA POWER to model forcing format
- **Dependencies**: s1_domain
- **From documentation**:
  - Define target sites: Update `station_list.lst` to include the latitude and longitude of the sites you would like SNOWPACK forcing files for. See `station_list.lst` for an example which would create .smet forcing files at 5 locations on the Antarctic ice sheet.
  - Postprocessing: Concatenate and zip individual yearly atmospheric forcing files into a continous time series located at `output/smet_forcing.zip`. `postprocess.sh` requires the atmospheric model as an argument, for example:

### Stage 5: Model Parameters (`s5_parameters`)

- **Description**: Set calibration parameters or defaults
- **Dependencies**: s2_soil, s3_vegetation
- **From documentation**:
  - Modify the `io_files/<model>.ini` to have DEMFILE and SOURCE_DEM point to the DEM, and METEOPATH and GRID2DPATH to the paths containing NetCDF files with the parameters
  - Postprocessing: Concatenate and zip individual yearly atmospheric forcing files into a continous time series located at `output/smet_forcing.zip`. `postprocess.sh` requires the atmospheric model as an argument, for example:

### Stage 6: Model Execution (`s6_run`)

- **Description**: Run the model binary
- **Dependencies**: s4_forcing, s5_parameters
- **From documentation**:
  - Modify the `io_files/<model>.ini` to have DEMFILE and SOURCE_DEM point to the DEM, and METEOPATH and GRID2DPATH to the paths containing NetCDF files with the parameters
  - Postprocessing: Concatenate and zip individual yearly atmospheric forcing files into a continous time series located at `output/smet_forcing.zip`. `postprocess.sh` requires the atmospheric model as an argument, for example:

### Stage 7: Output Parsing (`s7_postprocess`)

- **Description**: Extract discharge, soil moisture, ET from model output
- **Dependencies**: s6_run
- **From documentation**:
  - Postprocessing: Concatenate and zip individual yearly atmospheric forcing files into a continous time series located at `output/smet_forcing.zip`. `postprocess.sh` requires the atmospheric model as an argument, for example:

### Stage 8: River Routing (optional) (`s8_routing`)

- **Description**: Route runoff through river network if model doesn't include routing
- **Dependencies**: s7_postprocess
