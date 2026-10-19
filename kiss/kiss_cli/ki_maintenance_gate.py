"""Additive maintenance dispatch; legacy policy implementation stays immutable."""
from . import ki_maintenance_dispatch as legacy


def verifier(report):
    from . import ki_maintenance_epanet as epanet
    if isinstance(report, dict) and report.get("gate_policy") == epanet.POLICY:
        if report.get("maintenance_recipe") != epanet.RECIPE:
            raise ValueError("Unsupported EPANET maintenance recipe")
        return epanet
    return legacy.verifier(report)


def require_current(candidate, report, *, source=None):
    return verifier(report).require_current(candidate, report, source=source)


def recipe_verifier(recipe):
    from . import ki_maintenance_epanet as epanet
    return epanet if recipe == epanet.RECIPE else legacy.recipe_verifier(recipe)


def apply_recipe(candidate, *, source, recipe, name, **kwargs):
    from . import ki_maintenance_epanet as epanet
    if recipe == epanet.RECIPE:
        return epanet.apply_recipe(candidate, source=source, recipe=recipe, name=name, **kwargs)
    return legacy.apply_recipe(candidate, source=source, recipe=recipe, name=name, **kwargs)
