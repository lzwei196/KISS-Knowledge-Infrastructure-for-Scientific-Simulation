#!/home/server/knowledge-dissection-toolkit/auto_dissect/_work/PyMT/venv/bin/python
"""Discover installed BMI model plugins available in PyMT.

Purpose:
    Enumerate all BMI-enabled models registered as PyMT plugins via
    the entry-point system. Reports model name, class, module, and
    available input/output variable names.

Usage:
    python discover_models.py [--format json|table] [--output FILE]

Critical Rules:
    - Models must be installed as separate packages (e.g., pymt_cem)
    - An empty list does NOT mean PyMT is broken — it means no model
      plugins are installed
    - Plugin discovery uses pkg_resources entry points; ensure the
      model package is installed in the same environment as PyMT
"""

import argparse
import json
import sys
import importlib


def validate_inputs(args):
    """Check that PyMT is importable and environment is valid."""
    errors = []

    try:
        import pymt
    except ImportError:
        errors.append("PyMT is not installed. Run: pip install pymt")

    if args.output and not args.output.endswith(('.json', '.csv', '.txt')):
        errors.append(f"Unsupported output format: {args.output}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def discover_plugins():
    """Find all registered PyMT model plugins via entry points."""
    try:
        from importlib.metadata import entry_points
        eps = entry_points()
        if hasattr(eps, 'select'):
            pymt_eps = eps.select(group='pymt.plugins')
        else:
            pymt_eps = eps.get('pymt.plugins', [])
    except ImportError:
        import pkg_resources
        pymt_eps = pkg_resources.iter_entry_points(group='pymt.plugins')

    models = []
    for ep in pymt_eps:
        info = {
            "name": ep.name,
            "module": ep.value if hasattr(ep, 'value') else str(ep),
            "loaded": False,
            "input_vars": [],
            "output_vars": [],
            "error": None,
        }
        try:
            cls = ep.load()
            info["loaded"] = True
            info["class"] = cls.__name__
            # Try to get var names without initializing
            if hasattr(cls, 'input_var_names'):
                try:
                    info["input_vars"] = list(cls.input_var_names)
                except Exception:
                    pass
            if hasattr(cls, 'output_var_names'):
                try:
                    info["output_vars"] = list(cls.output_var_names)
                except Exception:
                    pass
        except Exception as e:
            info["error"] = str(e)

        models.append(info)

    return models


def process(args):
    """Main discovery logic."""
    validate_inputs(args)

    # Also try the PyMT MODELS collection
    models_from_collection = []
    try:
        from pymt import MODELS
        for name in MODELS:
            models_from_collection.append(name)
    except Exception:
        pass

    # Plugin-level discovery
    plugins = discover_plugins()

    result = {
        "status": "success",
        "pymt_version": None,
        "models_collection": models_from_collection,
        "plugins": plugins,
        "total_plugins": len(plugins),
        "loadable_plugins": sum(1 for p in plugins if p["loaded"]),
    }

    try:
        import pymt
        result["pymt_version"] = pymt.__version__
    except Exception:
        pass

    return result


def format_table(result):
    """Format discovery results as a human-readable table."""
    lines = []
    lines.append(f"PyMT Version: {result['pymt_version']}")
    lines.append(f"Total Plugins: {result['total_plugins']}")
    lines.append(f"Loadable: {result['loadable_plugins']}")
    lines.append("")
    lines.append(f"{'Name':<25} {'Loaded':<8} {'Module':<40}")
    lines.append("-" * 73)

    for p in result["plugins"]:
        loaded = "YES" if p["loaded"] else "NO"
        module = p.get("module", "?")[:40]
        lines.append(f"{p['name']:<25} {loaded:<8} {module:<40}")

    if result["models_collection"]:
        lines.append("")
        lines.append("Models in MODELS collection:")
        for name in result["models_collection"]:
            lines.append(f"  - {name}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Discover installed PyMT BMI model plugins"
    )
    parser.add_argument(
        "--format", choices=["json", "table"], default="table",
        help="Output format (default: table)"
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output file path (default: stdout)"
    )
    args = parser.parse_args()

    result = process(args)

    if args.format == "json":
        output_text = json.dumps(result, indent=2)
    else:
        output_text = format_table(result)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_text)
        print(f"Results written to {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
