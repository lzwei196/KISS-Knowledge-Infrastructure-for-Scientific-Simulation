#!/usr/bin/env python3
"""
assemble_pywr_model.py — Assemble a complete Pywr JSON model from components.

Takes outputs from previous stages (reservoir properties, inflow CSV, operating rules,
demand nodes) and generates a complete, validated Pywr model JSON file.

Network topology:
    [Catchment (inflow)] --> [Reservoir (storage)] --> [Release link]
                                                          |
                                        +--------+--------+--------+
                                        |        |        |        |
                                    [Env.flow] [Irr.] [Municipal] [Spill]

Usage:
    python assemble_pywr_model.py \
        --reservoir_json reservoir_props.json \
        --inflow_csv inflow.csv \
        --rules_json operating_rules.json \
        --demands_json demands.json \
        --start_date 1980-01-01 --end_date 1990-12-31 \
        --output model.json

    # Minimal model (reservoir + inflow only, no demands):
    python assemble_pywr_model.py \
        --reservoir_json reservoir_props.json \
        --inflow_csv inflow.csv \
        --start_date 1980-01-01 --end_date 1990-12-31 \
        --output model.json

Output:
    Complete Pywr JSON model file.
    Exit codes: 0 = success, 2 = input error, 3 = validation error
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


def build_timestepper(start_date, end_date, timestep=1):
    """Build Pywr timestepper block."""
    return {
        "start": start_date,
        "end": end_date,
        "timestep": timestep
    }


def build_inflow_node(inflow_csv_path, node_name="catchment_inflow"):
    """Build catchment inflow node with dataframe parameter."""
    return {
        "node": {
            "name": node_name,
            "type": "catchment",
            "flow": {
                "type": "dataframe",
                "url": str(inflow_csv_path),
                "index_col": "date",
                "parse_dates": True,
                "column": "inflow_m3s"
            }
        },
        "parameters": {}
    }


def build_storage_node(reservoir_props):
    """Build reservoir storage node from properties."""
    pywr_node = reservoir_props.get("pywr_node", {})
    name = pywr_node.get("name", reservoir_props.get("name", "reservoir"))

    return {
        "name": name,
        "type": "storage",
        "max_volume": reservoir_props["storage"]["max_volume_m3"],
        "min_volume": reservoir_props["storage"]["min_volume_m3"],
        "initial_volume": reservoir_props["storage"]["initial_volume_m3"],
        "cost": -500
    }


def build_release_node(reservoir_name, rules_params=None):
    """Build release link node."""
    name = f"{reservoir_name}_release"

    node = {
        "name": name,
        "type": "link",
    }

    if rules_params and f"{reservoir_name}_max_release_m3s" in rules_params:
        node["max_flow"] = f"{reservoir_name}_max_release_m3s"
    else:
        node["max_flow"] = 1e6  # Unconstrained

    return node


def build_spill_node(reservoir_name):
    """Build spillway node (uncontrolled overflow)."""
    return {
        "name": f"{reservoir_name}_spill",
        "type": "link",
        "cost": 1000  # Very high cost = last resort
    }


def build_downstream_node(reservoir_name):
    """Build downstream river node (receives release + spill)."""
    return {
        "name": f"{reservoir_name}_downstream",
        "type": "output",
        "cost": -10
    }


def build_edges(inflow_name, storage_name, release_name, spill_name,
                downstream_name, demand_nodes):
    """Build edge list connecting all nodes."""
    edges = [
        # Inflow -> Reservoir
        [inflow_name, storage_name],
        # Reservoir -> Release link
        [storage_name, release_name],
        # Reservoir -> Spillway
        [storage_name, spill_name],
        # Release -> Downstream
        [release_name, downstream_name],
        # Spill -> Downstream
        [spill_name, downstream_name],
    ]

    # Add demand edges (release -> demand)
    for demand in demand_nodes:
        dname = demand["name"]
        edges.append([release_name, dname])

    return edges


def build_recorders(storage_name, release_name, spill_name, demand_nodes):
    """Build recorder definitions for output timeseries."""
    recorders = {
        f"{storage_name}_storage_recorder": {
            "type": "numpyarraynode",
            "node": storage_name,
            "comment": "Record storage volume timeseries"
        },
        f"{release_name}_flow_recorder": {
            "type": "numpyarraynode",
            "node": release_name,
            "comment": "Record release flow timeseries"
        },
        f"{spill_name}_flow_recorder": {
            "type": "numpyarraynode",
            "node": spill_name,
            "comment": "Record spill flow timeseries"
        },
        f"{storage_name}_storage_stats": {
            "type": "numpyarraystoragerecorder",
            "node": storage_name,
            "comment": "Record storage volume timeseries (m3)"
        },
    }

    # Demand recorders
    for demand in demand_nodes:
        dname = demand["name"]
        recorders[f"{dname}_flow_recorder"] = {
            "type": "numpyarraynode",
            "node": dname,
            "comment": f"Record {demand.get('demand_type', 'demand')} supply"
        }

    return recorders


# Seconds per day — Pywr daily timestep treats a "flow" value as volume per timestep,
# so m3/s inputs (inflow CSV, release/demand profiles) must be converted to m3/day to
# stay consistent with storage volumes that are stored in m3.
_SECONDS_PER_DAY = 86400.0
# Downstream output node benefit (set in build_downstream_node); the control-curve
# above-curve cost must exceed this magnitude or the curve never holds the reservoir.
_DOWNSTREAM_BENEFIT = 10.0


def wire_control_curve_and_units(model, storage_name):
    """Post-process an assembled model to (1) wire the monthly control curve into the
    storage node's cost via a ControlCurveParameter (fixes triplet dt_pywr_006 — without
    this the LP just fills to max or empties to min with no intermediate regulation), and
    (2) rescale m3/s inputs to m3/day so flows are consistent with m3 storage volumes."""
    params = model.setdefault("parameters", {})

    # --- (1) control curve -> storage cost ---
    cc_name = f"{storage_name}_control_curve"
    if cc_name in params:
        above = params.get(f"{storage_name}_above_curve_cost", {}).get("value", 50.0)
        below = params.get(f"{storage_name}_below_curve_cost", {}).get("value", -500.0)
        if above <= _DOWNSTREAM_BENEFIT:           # legacy rules.json shipped above=1.0
            above = 50.0
        cost_name = f"{storage_name}_cost"
        params[cost_name] = {
            "type": "controlcurve",
            "storage_node": storage_name,
            "control_curve": cc_name,
            "values": [above, below],
            "comment": "dt_pywr_006 fix: storage cost from monthly control curve "
                       "(above-curve -> release toward target; below-curve -> refill)",
        }
        for node in model["nodes"]:
            if node.get("type") == "storage" and node.get("name") == storage_name:
                node["cost"] = cost_name

    # --- (2) units: m3/s -> m3/day ---
    # inflow dataframe on the catchment node
    for node in model["nodes"]:
        if node.get("type") == "catchment" and isinstance(node.get("flow"), dict) \
                and node["flow"].get("type") == "dataframe":
            df_param = node["flow"]
            node["flow"] = {
                "type": "aggregated",
                "agg_func": "product",
                "parameters": [df_param, {"type": "constant", "value": _SECONDS_PER_DAY}],
                "comment": "m3/s inflow CSV scaled to m3/day for daily timestep",
            }
    # m3/s rate parameters (release profiles, demand max_flow, env/min release)
    for k, v in list(params.items()):
        if not isinstance(v, dict):
            continue
        if k.endswith("_m3s") or k.endswith("_max_flow"):
            if v.get("type") in ("monthlyprofile", "dailyprofile") and "values" in v:
                v["values"] = [x * _SECONDS_PER_DAY for x in v["values"]]
                v["comment"] = (v.get("comment", "") + " [m3/s -> m3/day]").strip()
            elif v.get("type") == "constant" and "value" in v:
                v["value"] = v["value"] * _SECONDS_PER_DAY
                v["comment"] = (v.get("comment", "") + " [m3/s -> m3/day]").strip()
    # literal "unconstrained" max_flow on the release link (1e6 m3/s sentinel)
    for node in model["nodes"]:
        if node.get("type") == "link" and node.get("max_flow") == 1e6:
            node["max_flow"] = 1e12
    return model


def validate_model(model):
    """Validate model JSON structure before writing."""
    issues = []

    # Check required sections
    for section in ["metadata", "timestepper", "nodes", "edges"]:
        if section not in model:
            issues.append(f"Missing required section: {section}")

    # Check all edge references exist
    if "nodes" in model and "edges" in model:
        node_names = {n["name"] for n in model["nodes"]}
        for edge in model["edges"]:
            for name in edge:
                if name not in node_names:
                    issues.append(f"Edge references non-existent node: {name}")

    # Check parameter references
    if "parameters" in model and "nodes" in model:
        param_names = set(model["parameters"].keys())
        for node in model["nodes"]:
            for key in ["max_flow", "min_flow", "cost"]:
                val = node.get(key)
                if isinstance(val, str) and val not in param_names:
                    issues.append(
                        f"Node '{node['name']}' references unknown parameter: {val}"
                    )

    return issues


def main():
    parser = argparse.ArgumentParser(
        description="Assemble complete Pywr model JSON from components"
    )

    parser.add_argument("--reservoir_json", type=str, required=True,
                        help="Reservoir properties JSON")
    parser.add_argument("--inflow_csv", type=str, required=True,
                        help="Inflow timeseries CSV")
    parser.add_argument("--rules_json", type=str, default=None,
                        help="Operating rules JSON (optional)")
    parser.add_argument("--demands_json", type=str, default=None,
                        help="Demand definitions JSON (optional)")

    parser.add_argument("--start_date", type=str, required=True,
                        help="Simulation start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", type=str, required=True,
                        help="Simulation end date (YYYY-MM-DD)")
    parser.add_argument("--timestep", type=int, default=1,
                        help="Timestep in days (default: 1)")

    parser.add_argument("--title", type=str, default=None,
                        help="Model title for metadata")
    parser.add_argument("--output", type=str, required=True,
                        help="Output model JSON file path")

    args = parser.parse_args()

    try:
        # ── Load components ──
        with open(args.reservoir_json, "r") as f:
            reservoir_props = json.load(f)

        # Validate inflow CSV exists and has data
        inflow_path = Path(args.inflow_csv)
        if not inflow_path.exists():
            print(json.dumps({"error": f"Inflow CSV not found: {args.inflow_csv}"}))
            sys.exit(2)

        inflow_df = pd.read_csv(inflow_path, parse_dates=["date"])
        if len(inflow_df) == 0:
            print(json.dumps({"error": "Inflow CSV is empty"}))
            sys.exit(2)

        # Load operating rules if provided
        rules_params = {}
        if args.rules_json:
            with open(args.rules_json, "r") as f:
                rules_data = json.load(f)
            rules_params = rules_data.get("pywr_parameters", {})

        # Load demands if provided
        demand_nodes_list = []
        if args.demands_json:
            with open(args.demands_json, "r") as f:
                demands_data = json.load(f)
            demand_nodes_list = demands_data.get("demands", [])

        # ── Build model ──
        res_name = reservoir_props.get("name", "reservoir").replace(" ", "_")
        inflow_name = f"{res_name}_inflow"
        release_name = f"{res_name}_release"
        spill_name = f"{res_name}_spill"
        downstream_name = f"{res_name}_downstream"

        # Nodes
        nodes = []

        # 1. Inflow node
        inflow_result = build_inflow_node(
            str(inflow_path.resolve()), inflow_name
        )
        nodes.append(inflow_result["node"])

        # 2. Storage node
        storage_node = build_storage_node(reservoir_props)
        storage_node["name"] = res_name
        nodes.append(storage_node)

        # 3. Release link
        release_node = build_release_node(res_name, rules_params)
        nodes.append(release_node)

        # 4. Spillway
        spill_node = build_spill_node(res_name)
        nodes.append(spill_node)

        # 5. Downstream (catch-all output)
        downstream_node = build_downstream_node(res_name)
        nodes.append(downstream_node)

        # 6. Demand nodes
        demand_pywr_nodes = []
        for demand in demand_nodes_list:
            pywr_node = demand.get("pywr_node", {})
            if pywr_node:
                nodes.append(pywr_node)
                demand_pywr_nodes.append(pywr_node)

        # Edges
        edges = build_edges(
            inflow_name, res_name, release_name, spill_name,
            downstream_name,
            demand_pywr_nodes
        )

        # Parameters
        parameters = dict(rules_params)

        # Add demand parameters that are embedded in nodes
        for node in nodes:
            for key in ["max_flow", "min_flow", "cost"]:
                val = node.get(key)
                if isinstance(val, dict) and "type" in val:
                    param_name = f"{node['name']}_{key}"
                    parameters[param_name] = val
                    node[key] = param_name

        # Recorders
        recorders = build_recorders(
            res_name, release_name, spill_name, demand_pywr_nodes
        )

        # ── Assemble model ──
        title = args.title or f"Pywr model: {res_name}"

        model = {
            "metadata": {
                "title": title,
                "description": f"Reservoir operations model for {res_name}",
                "generator": "HydroCraft Pywr Knowledge Infrastructure",
                "reservoir": {
                    "name": reservoir_props.get("name"),
                    "capacity_mcm": reservoir_props["storage"]["max_volume_mcm"],
                    "dam_height_m": reservoir_props["geometry"]["dam_height_m"],
                },
            },
            "timestepper": build_timestepper(
                args.start_date, args.end_date, args.timestep
            ),
            "solver": {
                "name": "glpk"
            },
            "nodes": nodes,
            "edges": edges,
            "parameters": parameters,
            "recorders": recorders,
        }

        # ── Wire control curve into storage cost + fix m3/s -> m3/day units ──
        wire_control_curve_and_units(model, res_name)

        # ── Validate ──
        issues = validate_model(model)
        if issues:
            model["_validation_warnings"] = issues

        # ── Write output ──
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(model, f, indent=2)

        summary = {
            "status": "OK" if not issues else "WARNING",
            "output_file": str(out_path),
            "nodes": len(nodes),
            "edges": len(edges),
            "parameters": len(parameters),
            "recorders": len(recorders),
            "period": f"{args.start_date} to {args.end_date}",
            "inflow_days": len(inflow_df),
            "validation_issues": issues,
        }
        print(json.dumps(summary, indent=2))
        sys.exit(0 if not issues else 3)

    except Exception as e:
        import traceback
        print(json.dumps({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "status": "FAIL"
        }))
        sys.exit(3)


if __name__ == "__main__":
    main()
