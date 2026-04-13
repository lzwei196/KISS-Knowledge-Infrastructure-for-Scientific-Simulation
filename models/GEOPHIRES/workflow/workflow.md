# GEOPHIRES — Workflow

Auto-generated pipeline with 9 stages.

## Pipeline Stages

### Stage 0: Configuration (`s0_config`)

- **Description**: Set basin, period, resolution, paths
- **Dependencies**: none

### Stage 1: Domain / Grid Setup (`s1_domain`)

- **Description**: Define computational grid or HRUs from DEM and basin shapefile
- **Dependencies**: none

### Stage 2: Soil Parameters (`s2_soil`)

- **Description**: Derive soil hydraulic properties from HWSD or SoilGrids
- **Dependencies**: s1_domain
- **From documentation**:
  - Think carefully about the ordering of the calculations, and when the values you wish to use are valid.  If you are extending the Reservoir object, note that the parent Reservoir output parameters are only valid after the parent class Calculate method has been run.  It may also be possible that output values from one class may be altered later by the Calculate method on other classes.  GEOPHIRES-X core code tries to avoid this, as it is confusing, but it is possible, so know your variables!
  - The parent class as input parameters which will be set to valid default values after the parent __init__ method is called, but note that any of these values could be changed when the read_parameter method for that class is called.  And other unrelated parameters might also change due to dependencies, so don’t rely on the input parameters to be finalized until after read_parameter on the parent has run.  Normally, input parameters for a class don’t change after read_parameter for that class has run, but it does happen sometimes.  GEOPHIRES-X core code tries to avoid this, as it is confusing, but it is possible, so know your variables!

### Stage 3: Vegetation / Land Cover (`s3_vegetation`)

- **Description**: Classify land cover from AVHRR into model vegetation classes
- **Dependencies**: s1_domain

### Stage 4: Meteorological Forcing (`s4_forcing`)

- **Description**: Convert CMFD/MSWX/NASA POWER to model forcing format
- **Dependencies**: s1_domain

### Stage 5: Model Parameters (`s5_parameters`)

- **Description**: Set calibration parameters or defaults
- **Dependencies**: s2_soil, s3_vegetation
- **From documentation**:
  - Think carefully about the ordering of the calculations, and when the values you wish to use are valid.  If you are extending the Reservoir object, note that the parent Reservoir output parameters are only valid after the parent class Calculate method has been run.  It may also be possible that output values from one class may be altered later by the Calculate method on other classes.  GEOPHIRES-X core code tries to avoid this, as it is confusing, but it is possible, so know your variables!
  - The parent class as input parameters which will be set to valid default values after the parent __init__ method is called, but note that any of these values could be changed when the read_parameter method for that class is called.  And other unrelated parameters might also change due to dependencies, so don’t rely on the input parameters to be finalized until after read_parameter on the parent has run.  Normally, input parameters for a class don’t change after read_parameter for that class has run, but it does happen sometimes.  GEOPHIRES-X core code tries to avoid this, as it is confusing, but it is possible, so know your variables!

### Stage 6: Model Execution (`s6_run`)

- **Description**: Run the model binary
- **Dependencies**: s4_forcing, s5_parameters

### Stage 7: Output Parsing (`s7_postprocess`)

- **Description**: Extract discharge, soil moisture, ET from model output
- **Dependencies**: s6_run
- **From documentation**:
  - Think carefully about the ordering of the calculations, and when the values you wish to use are valid.  If you are extending the Reservoir object, note that the parent Reservoir output parameters are only valid after the parent class Calculate method has been run.  It may also be possible that output values from one class may be altered later by the Calculate method on other classes.  GEOPHIRES-X core code tries to avoid this, as it is confusing, but it is possible, so know your variables!

### Stage 8: River Routing (optional) (`s8_routing`)

- **Description**: Route runoff through river network if model doesn't include routing
- **Dependencies**: s7_postprocess
