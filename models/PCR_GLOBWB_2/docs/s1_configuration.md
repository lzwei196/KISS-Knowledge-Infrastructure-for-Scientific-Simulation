# Stage 1: Configuration and Domain Setup

## Purpose

Set up the PCR-GLOBWB 2 simulation domain by preparing the clone map, landmask, and configuring the .ini file. This stage defines the spatial extent, resolution, time period, and all model options.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Clone map | PCRaster .map | User-provided or from examples | Defines spatial resolution and extent |
| Landmask | PCRaster .map | User-provided or `None` | Restricts computation to area of interest |
| Input data | NetCDF via OPeNDAP or local | 4TU.ResearchData or local | All parameter and forcing files |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Configuration .ini file | INI text file | Complete model configuration |
| Clone map (local) | PCRaster .map | Local copy of spatial extent definition |
| Landmask (local) | PCRaster .map | Local copy of area mask |

## Procedure

1. **Choose spatial resolution**: 5 arcmin (~10 km) or 30 arcmin (~50 km)
2. **Obtain clone map**: Extract from `clone_landmask_maps/clone_landmask_examples.zip` or create custom
3. **Verify clone map properties**:
   - Must be in PCRaster format
   - Corner coordinates must be "nicely-rounded" integers (dt_011)
   - Must be stored locally (dt_010) — cannot be on OPeNDAP
4. **Edit .ini file** from template (e.g., `config/setup_05min.ini`):
   - Set `outputDir` to writable local path
   - Set `cloneMap` to local clone map path
   - Set `landmask` to local landmask or `None`
   - Set `inputDir` (OPeNDAP URL or local path)
   - Set `startTime` and `endTime` (YYYY-MM-DD)
   - Configure land cover, groundwater, routing sections
5. **Verify data access**: Test OPeNDAP URL connectivity if using remote data

## Verification

- [ ] Clone map loads in PCRaster: `pcrcalc --clone clonemap.map clone.map = boolean(1)`
- [ ] All .ini sections present: globalOptions, meteoOptions, landSurfaceOptions, forestOptions, grasslandOptions, irrPaddyOptions, irrNonPaddyOptions, groundwaterOptions, routingOptions, reportingOptions
- [ ] outputDir is writable
- [ ] startTime < endTime in valid YYYY-MM-DD format

## Traps

| Trap ID | Description | Silent? |
|---------|-------------|---------|
| dt_010 | Clone map must be local file, not OPeNDAP | No — immediate crash |
| dt_011 | Clone map corners must be integer coordinates | Yes — spatial misalignment |
| dt_012 | Only daily timestep supported | No — logged error |
| dt_014 | OPeNDAP is 10-100x slower than local files | Yes — just slow |

## Example

```bash
# Extract clone map for Rhine-Meuse basin
unzip clone_landmask_maps/clone_landmask_examples.zip -d /local/path/
# Verify it works
python -c "import pcraster; pcraster.setclone('/local/path/RhineMeuse05min.clone.map'); print('OK')"

# Edit config
cp config/setup_05min.ini my_setup.ini
# Set: outputDir = /scratch/my_output/
# Set: cloneMap = /local/path/RhineMeuse05min.clone.map
```
