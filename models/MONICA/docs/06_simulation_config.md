# Stage 6: Simulation Configuration (sim.json)

## Purpose

Configure the MONICA simulation run by creating `sim.json`. This file ties
together all input files, sets the simulation period, configures model switches,
and defines output variables and events.

## Inputs

| Source              | Information needed                           |
|---------------------|----------------------------------------------|
| Climate data range  | Start and end dates for climate.csv          |
| Output requirements | Variables of interest, temporal resolution   |
| Model options       | Irrigation, N-response, CO₂ response, etc.  |

## Outputs

File: `sim.json` — JSON configuration file.

## Structure

```json
{
  "crop.json": "crop.json",
  "site.json": "site.json",
  "climate.csv": "climate.csv",

  "climate.csv-options": {
    "start-date": "1991-01-01",
    "end-date": "2000-12-31",
    "no-of-climate-file-header-lines": 2,
    "csv-separator": ";",
    "header-to-acd-names": {
      "iso-date": "iso-date",
      "tavg": "tavg",
      "tmin": "tmin",
      "tmax": "tmax",
      "wind": "wind",
      "globrad": "globrad",
      "precip": "precip",
      "relhumid": "relhumid"
    }
  },

  "debug?": false,
  "UseSecondaryYields": true,
  "NitrogenResponseOn": true,
  "WaterDeficitResponseOn": true,
  "EmergenceFloodingControlOn": false,
  "EmergenceMoistureControlOn": false,

  "output": { ... }
}
```

## Key Configuration Options

### Climate CSV Options

| Parameter                        | Type   | Description                            |
|----------------------------------|--------|----------------------------------------|
| start-date                       | string | First day of simulation (YYYY-MM-DD)  |
| end-date                         | string | Last day of simulation                 |
| no-of-climate-file-header-lines  | int    | Number of header rows (usually 2)     |
| csv-separator                    | string | Column delimiter (";" or ",")          |
| header-to-acd-names              | object | Column name mapping + unit conversion |

#### Column mapping with unit conversion

```json
"header-to-acd-names": {
  "globrad": ["globrad", "/", 100]
}
```

This divides the `globrad` column by 100 during reading. Available operators:
`"/"`, `"*"`.

### Model Switches

| Switch                          | Default | Effect when true                        |
|---------------------------------|---------|-----------------------------------------|
| NitrogenResponseOn              | true    | Crop responds to N deficiency           |
| WaterDeficitResponseOn          | true    | Crop responds to water stress           |
| UseSecondaryYields              | true    | Include straw/residue yield             |
| UseAutomaticIrrigation          | false   | Trigger irrigation at soil water deficit|
| UseNMinMineralFertilisingMethod | false   | Fertilise based on soil N-min target    |
| EmergenceFloodingControlOn      | false   | Prevent emergence under waterlogging    |
| EmergenceMoistureControlOn      | **true** (monica-parameters.h `pc_EmergenceMoistureControlOn{true}`) | Germination only if top-layer moisture > 20 % of capillary water — set **false** for irrigated NCP runs (validated multisite sim.json; dt_30) or a dry autumn seedbed stalls the crop until spring |

### Automatic Irrigation Parameters

```json
"AutoIrrigationParams": {
  "irrigationThreshold": 0.35,
  "irrigationAmount": [17, "mm"],
  "nitrateConcentration": [0, "mg dm-3"],
  "sulfateConcentration": [0, "mg dm-3"]
}
```

### Output Configuration

```json
"output": {
  "write-file?": true,
  "path-to-output": "./",
  "file-name": "out.csv",
  "csv-options": {
    "include-header-row": true,
    "include-units-row": true,
    "include-aggregation-rows": false,
    "csv-separator": ","
  },
  "events": [
    ["daily", "Date", "Crop", "Stage", "Yield", "LAI", "Height",
     "TraDef", "NDef", "Act_ET", "ET0", "Precip",
     ["Mois", [1, 20]], ["STemp", [1, 5]],
     ["NO3", [1, 3]], "NLeach", "Denit", "N2O",
     ["SOC", [1, 3]], "NEP", "Rh", "GPP"
    ]
  ]
}
```

## Procedure

1. **Set file paths** — ensure crop.json, site.json, climate.csv paths are correct
   (relative to sim.json location)
2. **Configure climate options** — match separator, header lines, column mapping
3. **Set date range** — must be within climate.csv date range
4. **Choose model switches** — enable/disable irrigation, N response, etc.
5. **Define output events** — select variables and temporal resolution
6. **Validate JSON** — no trailing commas, balanced brackets

## Verification

- [ ] All referenced files exist relative to sim.json
- [ ] Start date ≤ end date
- [ ] Date range within climate.csv coverage
- [ ] Climate CSV separator matches actual file
- [ ] Header-to-acd-names mapping correct
- [ ] Output events syntax valid
- [ ] JSON parses without errors

## Traps

| Symptom                          | Cause                                   | Fix                         |
|----------------------------------|------------------------------------------|-----------------------------|
| JSON parse error                 | Trailing comma after last array element  | Remove trailing comma       |
| No output despite successful run | `"write-file?"` set to false             | Set to true                 |
| Output columns missing           | Variable name typo in events             | Check MONICA output docs    |
| Wrong date range                 | start-date/end-date mismatch with climate| Align dates                 |
| Empty data, header only          | No climate data in date range            | Check date format in CSV    |

## Example

Minimal sim.json for Hohenfinow2 example:

```json
{
  "crop.json": "crop-min.json",
  "site.json": "site-min.json",
  "climate.csv": "climate.csv",
  "climate.csv-options": {
    "start-date": "1991-01-01",
    "end-date": "1997-12-31",
    "no-of-climate-file-header-lines": 2,
    "csv-separator": ";"
  },
  "debug?": false,
  "UseSecondaryYields": true,
  "NitrogenResponseOn": true,
  "WaterDeficitResponseOn": true,
  "output": {
    "write-file?": true,
    "file-name": "out.csv",
    "csv-options": {
      "include-header-row": true,
      "include-units-row": true,
      "csv-separator": ","
    },
    "events": [
      ["crop", "Date", "Crop", "Yield", "SumNUp", "TempSum"]
    ]
  }
}
```
