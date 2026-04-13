#!/usr/bin/env python3
"""
build_apsimx.py — Assemble an APSIM .apsimx simulation file from components.

Constructs a valid .apsimx JSON file from:
  - Weather file path (.met)
  - Soil JSON fragment (from convert_soil.py)
  - Crop parameters (cultivar, population, sowing rules)
  - Simulation period (start/end dates)
  - Report variable list
  - Management rules (fertilizer, irrigation)

The .apsimx file is a nested JSON tree with typed nodes ($type, Name, Children).
This tool validates the structure before writing.

CRITICAL:
  - $type fields must use full assembly-qualified names (e.g., "Models.Core.Simulation, Models")
  - The file version must match what APSIM expects (currently ~213)
  - Weather FileName uses %root% macro to resolve relative to .apsimx location
  - Population is plants/m², NOT plants/ha

Usage:
  python build_apsimx.py --output simulation.apsimx \\
      --met-file weather/site.met --soil-json soil.json \\
      --crop Wheat --cultivar Hartog --population 100 \\
      --sowing-date 2000-05-15 --start 2000-01-01 --end 2000-12-31 \\
      --row-spacing 250 --sowing-depth 30

  python build_apsimx.py --output simulation.apsimx \\
      --met-file weather/site.met --soil-json soil.json \\
      --crop Wheat --cultivar Hartog --population 100 \\
      --start 2000-01-01 --end 2005-12-31 \\
      --auto-sow --sow-window-start "1-May" --sow-window-end "1-Jul" \\
      --sow-rain-trigger 25 --sow-rain-days 7 \\
      --fertilise-at-sowing 50 --fertilise-type NO3N
"""

import argparse
import json
import os
import sys


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.met_file and not os.path.isfile(args.met_file):
        # May use %root% — just warn
        pass

    if args.soil_json and not os.path.isfile(args.soil_json):
        errors.append(f"Soil JSON file not found: {args.soil_json}")

    if args.population is not None and args.population > 1000:
        errors.append(
            f"Population {args.population} plants/m² seems too high. "
            f"APSIM uses plants/m², not plants/ha. Typical: 50-300 plants/m². "
            f"If you meant {args.population} plants/ha, use {args.population/10000:.1f}"
        )

    if args.start and args.end:
        from datetime import datetime
        try:
            s = datetime.strptime(args.start, "%Y-%m-%d")
            e = datetime.strptime(args.end, "%Y-%m-%d")
            if s >= e:
                errors.append(f"Start date ({args.start}) must be before end date ({args.end})")
        except ValueError as ex:
            errors.append(f"Invalid date format: {ex}. Use YYYY-MM-DD.")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def build_sowing_manager(args):
    """Build a Manager script for sowing rules."""
    if args.auto_sow:
        # Automatic sowing based on rainfall trigger
        window_start = args.sow_window_start or "1-May"
        window_end = args.sow_window_end or "1-Jul"
        rain_trigger = args.sow_rain_trigger or 25
        rain_days = args.sow_rain_days or 7
        pop = args.population or 100
        depth = args.sowing_depth or 30
        cultivar = args.cultivar or "Hartog"
        row_spacing = args.row_spacing or 250

        script = f"""using Models.PMF;
using Models.Core;
using System;

namespace Models
{{
    [Serializable]
    public class SowingRule : Model
    {{
        [Link] Clock Clock;
        [Link] Summary Summary;
        [Link] Plant Crop;
        [Link] Models.Climate.Weather Weather;

        [Description("Start of sowing window")]
        public string StartDate {{ get; set; }} = "{window_start}";
        [Description("End of sowing window")]
        public string EndDate {{ get; set; }} = "{window_end}";
        [Description("Cumulative rainfall trigger (mm)")]
        public double RainTrigger {{ get; set; }} = {rain_trigger};
        [Description("Days to accumulate rain")]
        public int RainDays {{ get; set; }} = {rain_days};

        [EventSubscribe("DoManagement")]
        private void OnDoManagement(object sender, EventArgs e)
        {{
            if (!Crop.IsAlive && DateUtilities.WithinDates(StartDate, Clock.Today, EndDate))
            {{
                double cumulativeRain = 0;
                // Simple rain check
                if (Weather.Rain >= RainTrigger / RainDays)
                {{
                    Crop.Sow(cultivar: "{cultivar}", population: {pop},
                             depth: {depth}, rowSpacing: {row_spacing});
                    Summary.WriteMessage(this, "Sowing on " + Clock.Today.ToString(), MessageType.Information);
                }}
            }}
        }}
    }}
}}"""
    else:
        # Fixed date sowing
        sow_date = args.sowing_date or "2000-05-15"
        pop = args.population or 100
        depth = args.sowing_depth or 30
        cultivar = args.cultivar or "Hartog"
        row_spacing = args.row_spacing or 250

        script = f"""using Models.PMF;
using Models.Core;
using System;

namespace Models
{{
    [Serializable]
    public class SowingRule : Model
    {{
        [Link] Clock Clock;
        [Link] Summary Summary;
        [Link] Plant Crop;

        [EventSubscribe("DoManagement")]
        private void OnDoManagement(object sender, EventArgs e)
        {{
            if (Clock.Today == new DateTime({sow_date.replace('-',',')}))
            {{
                if (!Crop.IsAlive)
                {{
                    Crop.Sow(cultivar: "{cultivar}", population: {pop},
                             depth: {depth}, rowSpacing: {row_spacing});
                }}
            }}
        }}
    }}
}}"""

    return {
        "$type": "Models.Manager, Models",
        "Code": script,
        "Name": "SowingRule",
        "Children": [],
    }


def build_harvest_manager(crop):
    """Build a Manager script for automatic harvest at maturity."""
    script = f"""using Models.PMF;
using Models.Core;
using System;

namespace Models
{{
    [Serializable]
    public class HarvestRule : Model
    {{
        [Link] Plant Crop;
        [Link] Summary Summary;
        [Link] Clock Clock;

        [EventSubscribe("DoManagement")]
        private void OnDoManagement(object sender, EventArgs e)
        {{
            if (Crop.IsReadyForHarvesting)
            {{
                Crop.Harvest();
                Crop.EndCrop();
                Summary.WriteMessage(this, "Harvested on " + Clock.Today.ToString(), MessageType.Information);
            }}
        }}
    }}
}}"""

    return {
        "$type": "Models.Manager, Models",
        "Code": script,
        "Name": "HarvestRule",
        "Children": [],
    }


def build_report(crop):
    """Build a Report model with standard crop variables."""
    return {
        "$type": "Models.Report, Models",
        "Name": "Report",
        "VariableNames": [
            "[Clock].Today",
            f"[{crop}].Phenology.Stage",
            f"[{crop}].Phenology.CurrentPhaseName",
            f"[{crop}].AboveGround.Wt",
            f"[{crop}].Grain.Wt",
            f"[{crop}].Leaf.LAI",
            f"[{crop}].Root.RootingDepth",
            f"[{crop}].Total.Wt",
            "[Soil].Water.ESW as ESW",
            "[Weather].Rain",
            "[Weather].MaxT",
            "[Weather].MinT",
            "[Weather].Radn",
        ],
        "EventNames": [
            "[Clock].DoReport",
        ],
        "Children": [],
    }


def build_daily_report():
    """Build a daily summary Report."""
    return {
        "$type": "Models.Report, Models",
        "Name": "DailyReport",
        "VariableNames": [
            "[Clock].Today",
            "[Weather].Rain",
            "[Weather].MaxT",
            "[Weather].MinT",
            "[Weather].Radn",
        ],
        "EventNames": [
            "[Clock].DoReport",
        ],
        "Children": [],
    }


def process(args):
    """Assemble the .apsimx JSON structure."""
    crop = args.crop or "Wheat"

    # Load soil JSON
    if args.soil_json and os.path.isfile(args.soil_json):
        with open(args.soil_json) as f:
            soil = json.load(f)
    else:
        # Minimal default soil
        soil = {
            "$type": "Models.Soils.Soil, Models",
            "Name": "Soil",
            "Children": [],
        }

    # Weather path — use %root% relative
    if args.met_file:
        met_abs = os.path.abspath(args.met_file)
        output_dir = os.path.dirname(os.path.abspath(args.output))
        try:
            met_rel = os.path.relpath(met_abs, output_dir)
            met_path = f"%root%/{met_rel}"
        except ValueError:
            met_path = met_abs
    else:
        met_path = "%root%/weather.met"

    # Build simulation tree
    zone_children = [
        build_report(crop),
        soil,
        {
            "$type": f"Models.PMF.Plant, Models",
            "ResourceName": f"Plant({crop})",
            "Name": crop,
            "Children": [],
        },
        {
            "$type": "Models.Surface.SurfaceOrganicMatter, Models",
            "ResourceName": "SurfaceOrganicMatter",
            "Name": "SurfaceOrganicMatter",
            "Children": [],
        },
        build_sowing_manager(args),
        build_harvest_manager(crop),
    ]

    # Add fertiliser at sowing if requested
    if args.fertilise_at_sowing:
        zone_children.append({
            "$type": "Models.Fertiliser, Models",
            "Name": "Fertiliser",
            "Children": [],
        })

    simulation = {
        "$type": "Models.Core.Simulations, Models",
        "ExplorerWidth": 300,
        "Version": 213,
        "Name": "Simulations",
        "Children": [
            {
                "$type": "Models.Storage.DataStore, Models",
                "useFirebird": False,
                "Name": "DataStore",
                "Children": [],
            },
            {
                "$type": "Models.Core.Simulation, Models",
                "Name": f"{crop}Simulation",
                "Enabled": True,
                "Children": [
                    {
                        "$type": "Models.Clock, Models",
                        "Start": f"{args.start}T00:00:00",
                        "End": f"{args.end}T00:00:00",
                        "Name": "Clock",
                        "Children": [],
                    },
                    {
                        "$type": "Models.Summary, Models",
                        "Name": "Summary",
                        "Children": [],
                    },
                    {
                        "$type": "Models.Climate.Weather, Models",
                        "FileName": met_path,
                        "Name": "Weather",
                        "Children": [],
                    },
                    {
                        "$type": "Models.MicroClimate, Models",
                        "Name": "MicroClimate",
                        "a_interception": 0.0,
                        "b_interception": 1.0,
                        "c_interception": 0.0,
                        "d_interception": 0.0,
                        "SoilHeatFluxFraction": 0.4,
                        "NightInterceptionFraction": 0.5,
                        "ReferenceHeight": 2.0,
                        "Children": [],
                    },
                    {
                        "$type": "Models.Core.Zone, Models",
                        "Area": 1.0,
                        "Slope": 0.0,
                        "Name": "Field",
                        "Children": zone_children,
                    },
                ],
            },
        ],
    }

    return {
        "status": "ok",
        "simulation": simulation,
        "crop": crop,
        "cultivar": args.cultivar or "Hartog",
        "period": f"{args.start} to {args.end}",
        "met_path": met_path,
    }


def validate_outputs(result):
    """Validate the assembled simulation structure."""
    warnings = []

    if result["status"] != "ok":
        return result

    sim = result["simulation"]

    # Check version
    if sim.get("Version", 0) < 200:
        warnings.append("File version < 200 — may need upgrading")

    # Check required children exist
    root_children = sim.get("Children", [])
    has_datastore = any("DataStore" in str(c.get("$type", "")) for c in root_children)
    has_simulation = any("Simulation" in str(c.get("$type", "")) for c in root_children)

    if not has_datastore:
        warnings.append("Missing DataStore — output will not be saved")
    if not has_simulation:
        warnings.append("Missing Simulation node")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Assemble APSIM .apsimx simulation file"
    )
    parser.add_argument("--output", required=True, help="Output .apsimx file path")
    parser.add_argument("--met-file", type=str, help="Path to .met weather file")
    parser.add_argument("--soil-json", type=str, help="Path to soil JSON (from convert_soil.py)")
    parser.add_argument("--crop", type=str, default="Wheat", help="Crop name")
    parser.add_argument("--cultivar", type=str, default="Hartog", help="Cultivar name")
    parser.add_argument("--population", type=float, default=100,
                        help="Sowing population (plants/m² — NOT plants/ha!)")
    parser.add_argument("--row-spacing", type=float, default=250, help="Row spacing (mm)")
    parser.add_argument("--sowing-depth", type=float, default=30, help="Sowing depth (mm)")
    parser.add_argument("--sowing-date", type=str, default=None,
                        help="Fixed sowing date (YYYY-MM-DD)")
    parser.add_argument("--start", type=str, required=True, help="Simulation start (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="Simulation end (YYYY-MM-DD)")
    # Auto-sowing options
    parser.add_argument("--auto-sow", action="store_true",
                        help="Use rainfall-triggered automatic sowing")
    parser.add_argument("--sow-window-start", type=str, default="1-May")
    parser.add_argument("--sow-window-end", type=str, default="1-Jul")
    parser.add_argument("--sow-rain-trigger", type=float, default=25,
                        help="Cumulative rain trigger (mm)")
    parser.add_argument("--sow-rain-days", type=int, default=7,
                        help="Days over which to accumulate rain")
    # Fertiliser
    parser.add_argument("--fertilise-at-sowing", type=float, default=None,
                        help="Fertiliser amount at sowing (kg N/ha)")
    parser.add_argument("--fertilise-type", type=str, default="NO3N",
                        help="Fertiliser type (NO3N, NH4N, UreaN)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    # Write .apsimx file
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result["simulation"], f, indent=2)

    # Print summary
    summary = {k: v for k, v in result.items() if k != "simulation"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
