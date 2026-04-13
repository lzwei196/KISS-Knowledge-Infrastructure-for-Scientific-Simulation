#!/usr/bin/env python3
"""BMI Compliance Checker.

Validates that a Python class correctly implements all 31 BMI functions
required by the BMI v2.0 specification.

Pipeline stage: S2 — Compliance Check
Pattern: validate_inputs → check_compliance → validate_outputs (report)
"""

import importlib
import inspect
import logging
import json
import sys
from typing import Any

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BMI v2.0 complete function specification
# ---------------------------------------------------------------------------

BMI_FUNCTIONS = {
    # Metadata
    "get_bmi_version": {
        "category": "metadata",
        "args": [],
        "returns": "str",
        "required_since": "2.1",
    },
    # Control
    "initialize": {
        "category": "control",
        "args": ["config_file: str"],
        "returns": "None",
    },
    "update": {
        "category": "control",
        "args": [],
        "returns": "None",
    },
    "update_until": {
        "category": "control",
        "args": ["time: float"],
        "returns": "None",
    },
    "finalize": {
        "category": "control",
        "args": [],
        "returns": "None",
    },
    # Information
    "get_component_name": {
        "category": "info",
        "args": [],
        "returns": "str",
    },
    "get_input_item_count": {
        "category": "info",
        "args": [],
        "returns": "int",
    },
    "get_output_item_count": {
        "category": "info",
        "args": [],
        "returns": "int",
    },
    "get_input_var_names": {
        "category": "info",
        "args": [],
        "returns": "tuple[str]",
    },
    "get_output_var_names": {
        "category": "info",
        "args": [],
        "returns": "tuple[str]",
    },
    # Variable information
    "get_var_grid": {
        "category": "variable",
        "args": ["name: str"],
        "returns": "int",
    },
    "get_var_type": {
        "category": "variable",
        "args": ["name: str"],
        "returns": "str",
    },
    "get_var_units": {
        "category": "variable",
        "args": ["name: str"],
        "returns": "str",
    },
    "get_var_itemsize": {
        "category": "variable",
        "args": ["name: str"],
        "returns": "int",
    },
    "get_var_nbytes": {
        "category": "variable",
        "args": ["name: str"],
        "returns": "int",
    },
    "get_var_location": {
        "category": "variable",
        "args": ["name: str"],
        "returns": "str",
    },
    # Time
    "get_current_time": {
        "category": "time",
        "args": [],
        "returns": "float",
    },
    "get_start_time": {
        "category": "time",
        "args": [],
        "returns": "float",
    },
    "get_end_time": {
        "category": "time",
        "args": [],
        "returns": "float",
    },
    "get_time_units": {
        "category": "time",
        "args": [],
        "returns": "str",
    },
    "get_time_step": {
        "category": "time",
        "args": [],
        "returns": "float",
    },
    # Getters/Setters
    "get_value": {
        "category": "getter_setter",
        "args": ["name: str", "dest: ndarray"],
        "returns": "ndarray",
    },
    "get_value_ptr": {
        "category": "getter_setter",
        "args": ["name: str"],
        "returns": "ndarray",
    },
    "get_value_at_indices": {
        "category": "getter_setter",
        "args": ["name: str", "dest: ndarray", "inds: ndarray"],
        "returns": "ndarray",
    },
    "set_value": {
        "category": "getter_setter",
        "args": ["name: str", "src: ndarray"],
        "returns": "None",
    },
    "set_value_at_indices": {
        "category": "getter_setter",
        "args": ["name: str", "inds: ndarray", "src: ndarray"],
        "returns": "None",
    },
    # Grid
    "get_grid_rank": {
        "category": "grid",
        "args": ["grid: int"],
        "returns": "int",
    },
    "get_grid_size": {
        "category": "grid",
        "args": ["grid: int"],
        "returns": "int",
    },
    "get_grid_type": {
        "category": "grid",
        "args": ["grid: int"],
        "returns": "str",
    },
    "get_grid_shape": {
        "category": "grid",
        "args": ["grid: int", "shape: ndarray"],
        "returns": "ndarray",
    },
    "get_grid_spacing": {
        "category": "grid",
        "args": ["grid: int", "spacing: ndarray"],
        "returns": "ndarray",
    },
    "get_grid_origin": {
        "category": "grid",
        "args": ["grid: int", "origin: ndarray"],
        "returns": "ndarray",
    },
    "get_grid_x": {
        "category": "grid",
        "args": ["grid: int", "x: ndarray"],
        "returns": "ndarray",
    },
    "get_grid_y": {
        "category": "grid",
        "args": ["grid: int", "y: ndarray"],
        "returns": "ndarray",
    },
    "get_grid_z": {
        "category": "grid",
        "args": ["grid: int", "z: ndarray"],
        "returns": "ndarray",
    },
    "get_grid_node_count": {
        "category": "grid",
        "args": ["grid: int"],
        "returns": "int",
    },
    "get_grid_edge_count": {
        "category": "grid",
        "args": ["grid: int"],
        "returns": "int",
    },
    "get_grid_face_count": {
        "category": "grid",
        "args": ["grid: int"],
        "returns": "int",
    },
    "get_grid_edge_nodes": {
        "category": "grid",
        "args": ["grid: int", "edge_nodes: ndarray"],
        "returns": "ndarray",
    },
    "get_grid_face_edges": {
        "category": "grid",
        "args": ["grid: int", "face_edges: ndarray"],
        "returns": "ndarray",
    },
    "get_grid_face_nodes": {
        "category": "grid",
        "args": ["grid: int", "face_nodes: ndarray"],
        "returns": "ndarray",
    },
    "get_grid_nodes_per_face": {
        "category": "grid",
        "args": ["grid: int", "nodes_per_face: ndarray"],
        "returns": "ndarray",
    },
}

VALID_GRID_TYPES = {
    "scalar",
    "points",
    "vector",
    "unstructured",
    "structured_quadrilateral",
    "rectilinear",
    "uniform_rectilinear",
}

VALID_VAR_LOCATIONS = {"node", "edge", "face"}


def validate_inputs(module_path: str, class_name: str) -> type:
    """Load and validate the BMI class.

    Parameters
    ----------
    module_path : str
        Python module path (e.g., 'heat.BmiHeat' or path to .py file).
    class_name : str
        Name of the class implementing BMI.

    Returns
    -------
    type
        The loaded BMI class.
    """
    try:
        if module_path.endswith(".py"):
            spec = importlib.util.spec_from_file_location("bmi_module", module_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        else:
            mod = importlib.import_module(module_path)
    except Exception as e:
        raise ImportError(f"Cannot import module '{module_path}': {e}")

    bmi_class = getattr(mod, class_name, None)
    if bmi_class is None:
        available = [
            name
            for name, obj in inspect.getmembers(mod, inspect.isclass)
            if not name.startswith("_")
        ]
        raise AttributeError(
            f"Class '{class_name}' not found in module. "
            f"Available classes: {available}"
        )

    if not inspect.isclass(bmi_class):
        raise TypeError(f"'{class_name}' is not a class")

    logger.info(f"Loaded BMI class: {module_path}.{class_name}")
    return bmi_class


def check_compliance(bmi_class: type) -> dict:
    """Check BMI compliance of the given class.

    Parameters
    ----------
    bmi_class : type
        The class to check for BMI compliance.

    Returns
    -------
    dict
        Compliance report with per-function results.
    """
    report = {
        "class_name": bmi_class.__name__,
        "total_functions": len(BMI_FUNCTIONS),
        "implemented": 0,
        "missing": 0,
        "warnings": [],
        "errors": [],
        "by_category": {},
        "details": {},
    }

    for func_name, spec in BMI_FUNCTIONS.items():
        category = spec["category"]
        if category not in report["by_category"]:
            report["by_category"][category] = {"pass": 0, "fail": 0}

        has_method = hasattr(bmi_class, func_name)
        is_callable = callable(getattr(bmi_class, func_name, None))

        if has_method and is_callable:
            report["implemented"] += 1
            report["by_category"][category]["pass"] += 1

            # Check method signature
            method = getattr(bmi_class, func_name)
            sig = inspect.signature(method)
            n_params = len(
                [
                    p
                    for p in sig.parameters.values()
                    if p.name != "self"
                ]
            )
            expected_n_params = len(spec["args"])

            if n_params != expected_n_params:
                report["warnings"].append(
                    f"{func_name}: expected {expected_n_params} args "
                    f"(excluding self), found {n_params}"
                )

            report["details"][func_name] = {
                "status": "pass",
                "category": category,
                "signature": str(sig),
            }
        else:
            report["missing"] += 1
            report["by_category"][category]["fail"] += 1
            report["errors"].append(f"Missing required function: {func_name}")
            report["details"][func_name] = {
                "status": "fail",
                "category": category,
                "reason": "not implemented",
            }

    # Summary
    report["compliance_pct"] = round(
        100 * report["implemented"] / report["total_functions"], 1
    )
    report["status"] = "PASS" if report["missing"] == 0 else "FAIL"

    return report


def validate_outputs(report: dict) -> bool:
    """Print and validate the compliance report.

    Parameters
    ----------
    report : dict
        Compliance report from check_compliance.

    Returns
    -------
    bool
        True if fully compliant.
    """
    print(f"\n{'='*60}")
    print(f"BMI Compliance Report: {report['class_name']}")
    print(f"{'='*60}")
    print(f"Status: {report['status']}")
    print(
        f"Functions: {report['implemented']}/{report['total_functions']} "
        f"({report['compliance_pct']}%)"
    )
    print()

    print("By category:")
    for cat, counts in report["by_category"].items():
        total = counts["pass"] + counts["fail"]
        marker = "PASS" if counts["fail"] == 0 else "FAIL"
        print(f"  {cat:20s} {counts['pass']}/{total:2d} [{marker}]")

    if report["errors"]:
        print(f"\nErrors ({len(report['errors'])}):")
        for err in report["errors"]:
            print(f"  - {err}")

    if report["warnings"]:
        print(f"\nWarnings ({len(report['warnings'])}):")
        for warn in report["warnings"]:
            print(f"  - {warn}")

    print(f"{'='*60}\n")

    return report["status"] == "PASS"


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Check BMI compliance of a Python class"
    )
    parser.add_argument(
        "module",
        help="Python module path or .py file",
    )
    parser.add_argument(
        "class_name",
        help="Name of the BMI class to check",
    )
    parser.add_argument(
        "--json",
        "-j",
        metavar="PATH",
        help="Write JSON report to file",
    )

    args = parser.parse_args()

    # validate → process → validate
    bmi_class = validate_inputs(args.module, args.class_name)
    report = check_compliance(bmi_class)
    is_compliant = validate_outputs(report)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        logger.info(f"JSON report written to {args.json}")

    sys.exit(0 if is_compliant else 1)


if __name__ == "__main__":
    main()
