"""Exact maintenance-policy dispatch without invalidating prior policy bytes.

Selection is not authorization: each target checks its own signature, policy,
source, exact generated change, KDT result and runtime evidence. Unknown policies
fail closed; no retired or stale policy is accepted as a compatibility fallback.
"""
from . import ki_maintenance as original


def verifier(report):
    from . import ki_maintenance_crop as crop
    if isinstance(report, dict):
        if report.get("gate_policy") == original.POLICY:
            return original
        if report.get("gate_policy") == crop.POLICY and report.get("maintenance_recipe") == crop.RECIPE:
            return crop
    raise ValueError("Unsupported maintenance verification policy")


def require_current(candidate, report, *, source=None):
    return verifier(report).require_current(candidate, report, source=source)


def recipe_verifier(recipe):
    from . import ki_maintenance_crop as crop
    if recipe == crop.RECIPE:
        return crop
    if recipe in {"tool_inventory", "preflight_reporting", "package_contract",
                  "wofost_parameter_routing", "wofost_runtime_paths"}:
        return original
    raise ValueError("Unsupported maintenance recipe")


def apply_recipe(candidate, *, source, recipe, name, **kwargs):
    target = recipe_verifier(recipe)
    if target is original:
        from . import ki_maintenance_recipes
        target = ki_maintenance_recipes
    return target.apply_recipe(candidate, source=source, recipe=recipe, name=name, **kwargs)
