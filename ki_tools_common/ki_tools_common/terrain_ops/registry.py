"""
registry.py — @geo_tool decorator for terrain_ops.

Lightweight tool-registry pattern adapted from opengeos/GeoAgent. Every
terrain_ops primitive is decorated with @geo_tool so agents (and humans)
can discover what's available via a single import.

Usage::

    from ki_tools_common.terrain_ops.registry import geo_tool, list_tools

    @geo_tool(
        name="delineate_basin",
        category="hydrology",
        description="Delineate a watershed from a DEM and pour point.",
    )
    def delineate_basin(dem_path, pour_point, output_dir, ...):
        ...

    # Anywhere:
    tools = list_tools()                       # all
    hydro = list_tools(category="hydrology")   # filtered

Discovery contract: no schema enforcement. Agents read each tool's
__doc__ + signature + the metadata block attached as ``fn.geo_tool_meta``.
"""

from typing import Callable, Dict, List, Optional

_REGISTRY: Dict[str, Callable] = {}


def geo_tool(
    name: Optional[str] = None,
    category: str = "general",
    description: str = "",
    requires: Optional[List[str]] = None,
) -> Callable:
    """Decorator: register a function as an agent-callable terrain tool.

    Args:
        name: Tool name (defaults to function name). Must be unique across the
            registry — collisions raise at import time.
        category: Free-form tag for filtering (e.g., "hydrology", "raster",
            "vector", "io"). Use the smallest sensible set.
        description: One-line description. Agents read this BEFORE inspecting
            the docstring, so keep it self-contained.
        requires: External binaries/packages the tool needs (e.g.,
            ["whitebox", "rasterio"]). Surfaced in list_tools() so an agent
            can check capability before calling.
    """
    def wrap(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        if tool_name in _REGISTRY:
            raise ValueError(
                f"geo_tool name collision: {tool_name!r} already registered as "
                f"{_REGISTRY[tool_name].__module__}.{_REGISTRY[tool_name].__name__}"
            )
        fn.geo_tool_meta = {
            "name": tool_name,
            "category": category,
            "description": description,
            "requires": list(requires or []),
            "module": fn.__module__,
            "qualname": fn.__qualname__,
        }
        _REGISTRY[tool_name] = fn
        return fn
    return wrap


def list_tools(category: Optional[str] = None) -> List[Dict]:
    """Return the metadata dict for every registered tool, optionally filtered."""
    out = []
    for fn in _REGISTRY.values():
        meta = dict(fn.geo_tool_meta)
        if category is not None and meta["category"] != category:
            continue
        out.append(meta)
    return out


def get_tool(name: str) -> Callable:
    """Look up a registered tool by name. Raises KeyError on miss."""
    if name not in _REGISTRY:
        raise KeyError(f"No geo_tool named {name!r}. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]
