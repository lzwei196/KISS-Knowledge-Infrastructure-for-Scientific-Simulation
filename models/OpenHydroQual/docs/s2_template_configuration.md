# S2: Template Configuration

## Purpose

Select and load the correct JSON component templates that define available block
types, link types, source types, and reaction kinetics for the model domain.
Template selection determines what physical processes the model can represent.

## Inputs

| Input                  | Location                 | Description                        |
|------------------------|--------------------------|------------------------------------|
| main_components.json   | resources/               | Core blocks, links, sources (required) |
| Domain-specific JSONs  | resources/               | Additional process templates       |
| settings.json          | resources/               | Solver and MCMC configuration      |

## Outputs

| Output                | Description                                              |
|-----------------------|----------------------------------------------------------|
| Template commands     | `loadtemplate` and `addtemplate` lines in the .ohq file  |
| Available types       | Block/link/source types available for model construction |

## Procedure

1. **Identify required processes**: Determine what physical/chemical processes
   the model needs. Map each to a template:

   | Process                    | Template                        |
   |----------------------------|---------------------------------|
   | Basic flow and storage     | main_components.json (always)   |
   | Groundwater flow           | unconfined_groundwater.json     |
   | Pipe networks              | pipe_pump_tank.json             |
   | Open channel flow          | open_channel.json               |
   | Unsaturated zone           | unsaturated_soil*.json          |
   | Sewer systems              | Sewer_system.json               |
   | Wastewater treatment       | wastewater.json                 |
   | River water quality        | river_processes.json            |
   | Sorption/mass transfer     | mass_transfer.json              |
   | Pollutant buildup/washoff  | buildup_washoff.json            |
   | Evapotranspiration         | evapotranspiration_models.json  |
   | Green infrastructure       | Bioretention.json, BioSwale.json|
   | Stormwater ponds           | StormwaterPond*.json            |
   | Pond processes             | Pond_Plugin.json                |

2. **Write template commands**: Add to the .ohq file header:
   ```
   loadtemplate; filename = /path/to/resources/main_components.json
   addtemplate; filename = /path/to/resources/river_processes.json
   addtemplate; filename = /path/to/resources/mass_transfer.json
   addtemplate; filename = /path/to/resources/evapotranspiration_models.json
   ```

3. **Verify template loading**: The model prints loaded template info to stdout.
   Check that all expected block types are available.

## Verification

- `loadtemplate` must appear exactly once (first command)
- `addtemplate` can appear multiple times for additional modules
- All referenced template files must exist at the specified paths
- Template paths must be absolute or resolvable from the binary location

## Traps

| Trap                                    | Impact | Prevention                           |
|-----------------------------------------|--------|--------------------------------------|
| Hardcoded developer paths in .ohq       | Fatal  | Replace with local paths             |
| Missing main_components.json            | Fatal  | Always load main_components first    |
| Template loaded twice                   | Silent | May cause type conflicts             |
| Wrong template for domain               | Silent | Model runs but wrong physics         |
| Template path with spaces               | Fatal  | Quote or escape spaces               |
| loadtemplate not first command           | Fatal  | Must be first line of .ohq           |

## Example

Wet pond model requiring ponds, river processes, mass transfer, and ET:

```
loadtemplate; filename = /opt/ohq/resources/main_components.json
addtemplate; filename = /opt/ohq/resources/Pond_Plugin.json
addtemplate; filename = /opt/ohq/resources/river_processes.json
addtemplate; filename = /opt/ohq/resources/mass_transfer.json
addtemplate; filename = /opt/ohq/resources/evapotranspiration_models.json
```

This gives access to block types: Pond, Bed_sediment, fixed_head, and
link types: wide_channel, wier, River_bed_sediment_link, plus
source types: atmospheric exchange, constant_source, Evapotranspiration_Penmam.
