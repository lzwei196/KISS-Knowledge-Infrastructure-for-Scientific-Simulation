# TOPMODEL — Workflow

Auto-generated pipeline with 9 stages.

## Pipeline Stages

### Stage 0: Configuration (`s0_config`)

- **Description**: Set basin, period, resolution, paths
- **Dependencies**: none

### Stage 1: Domain / Grid Setup (`s1_domain`)

- **Description**: Define computational grid or HRUs from DEM and basin shapefile
- **Dependencies**: none
- **From documentation**:
  - Download data from http://web.corral.tacc.utexas.edu/nfiedata/HAND/ for the desired HUC06 of interest
  - Edit the [workflow_hand_twi_giuh.env](./src/workflow_hand_twi_giuh.env) file. This file contains all parameters for the runs, including the HUC06 number, path to the hydrofabrics, and environmental variabels for TAUDEM and gdal
  - Run: source [workflow_hand_twi_giuh.sh](./src/workflow_hand_twi_giuh.sh)

### Stage 2: Soil Parameters (`s2_soil`)

- **Description**: Derive soil hydraulic properties from HWSD or SoilGrids
- **Dependencies**: s1_domain
- **From documentation**:
  - Edit the [workflow_hand_twi_giuh.env](./src/workflow_hand_twi_giuh.env) file. This file contains all parameters for the runs, including the HUC06 number, path to the hydrofabrics, and environmental variabels for TAUDEM and gdal

### Stage 3: Vegetation / Land Cover (`s3_vegetation`)

- **Description**: Classify land cover from AVHRR into model vegetation classes
- **Dependencies**: s1_domain
- **From documentation**:
  - Download data from http://web.corral.tacc.utexas.edu/nfiedata/HAND/ for the desired HUC06 of interest
  - Edit the [workflow_hand_twi_giuh.env](./src/workflow_hand_twi_giuh.env) file. This file contains all parameters for the runs, including the HUC06 number, path to the hydrofabrics, and environmental variabels for TAUDEM and gdal
  - Run: source [workflow_hand_twi_giuh.sh](./src/workflow_hand_twi_giuh.sh)

### Stage 4: Meteorological Forcing (`s4_forcing`)

- **Description**: Convert CMFD/MSWX/NASA POWER to model forcing format
- **Dependencies**: s1_domain

### Stage 5: Model Parameters (`s5_parameters`)

- **Description**: Set calibration parameters or defaults
- **Dependencies**: s2_soil, s3_vegetation
- **From documentation**:
  - Calculate a raster with the Topmodel topographic wetness index (TWI)
  - Generates the subcat.dat file needed to run topmodel - the file name contains the ID of the sub-basin.
  - Edit the [workflow_hand_twi_giuh.env](./src/workflow_hand_twi_giuh.env) file. This file contains all parameters for the runs, including the HUC06 number, path to the hydrofabrics, and environmental variabels for TAUDEM and gdal
  - `bmi.register_bmi_topmodel()`

### Stage 6: Model Execution (`s6_run`)

- **Description**: Run the model binary
- **Dependencies**: s4_forcing, s5_parameters
- **From documentation**:
  - Calculate a raster with the Topmodel topographic wetness index (TWI)
  - Generates the subcat.dat file needed to run topmodel - the file name contains the ID of the sub-basin.
  - `bmi.register_bmi_topmodel()`

### Stage 7: Output Parsing (`s7_postprocess`)

- **Description**: Extract discharge, soil moisture, ET from model output
- **Dependencies**: s6_run

### Stage 8: River Routing (optional) (`s8_routing`)

- **Description**: Route runoff through river network if model doesn't include routing
- **Dependencies**: s7_postprocess
