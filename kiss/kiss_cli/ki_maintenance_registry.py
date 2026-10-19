"""Additive discovery and routing for independently sealed maintenance recipes.

Routing does not authorize an edit: each selected verifier authenticates its own
exact policy, implementation and evidence. Keep older gates immutable so adding
a model does not invalidate already reviewed maintenance receipts.
"""
from . import ki_maintenance_gate as previous


def setup_recipe(ki_name):
    from . import setup_ki_repair
    if ki_name == "SHAW":
        from . import ki_maintenance_shaw as shaw
        return shaw.RECIPE
    return setup_ki_repair.recipe_for(ki_name)


def verifier(report):
    from . import ki_maintenance_shaw as shaw
    if isinstance(report, dict) and report.get("gate_policy") == shaw.POLICY:
        if report.get("maintenance_recipe") != shaw.RECIPE:
            raise ValueError("Unsupported SHAW maintenance recipe")
        return shaw
    return previous.verifier(report)


def require_current(candidate, report, *, source=None):
    return verifier(report).require_current(candidate, report, source=source)


def recipe_verifier(recipe):
    from . import ki_maintenance_shaw as shaw
    return shaw if recipe == shaw.RECIPE else previous.recipe_verifier(recipe)


def apply_recipe(candidate, *, source, recipe, name, **kwargs):
    from . import ki_maintenance_shaw as shaw
    if recipe == shaw.RECIPE:
        return shaw.apply_recipe(candidate, source=source, recipe=recipe, name=name, **kwargs)
    return previous.apply_recipe(candidate, source=source, recipe=recipe, name=name, **kwargs)
