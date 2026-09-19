"""flow.declared — the KI's own word on each input: how it is obtained, in what format.

FLOW-TARGET step 4: the agent chooses, it does not classify. Each inventory item
carries a host-attached ``declared`` block read from the KI's ``dag.yaml`` inputs
(``source_kind``, ``model_input_format``, ``unit``, ``notes``) plus the KI tool that
writes that format when there is one. From that the host decides the item's group:

  fetch    a catalogue dataset GeoForge brings in (served / clip / manual)
  you      the KI says user_provided and no default tool exists, or the plan says so
  run      everything else: a KI default method, a lookup tool, a step output, on disk

Nothing here trusts the agent's ``status`` or ``needs_user``; those are advisory.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

FETCH_KINDS = {"forcing", "observation", "gauge", "remote_sensing"}
RUN_KINDS = {"dataset_lookup", "calibrated", "derived", "computed", "upstream_model", "model_output"}
USER_KINDS = {"user_provided", "from_user", "user"}

_CATEGORY_HINTS = {
    "forcing": ("forcing", "weather", "meteorology", "meteorological", "climate", "met"),
    "initial_conditions": ("initial", "profiles", "ic"),
    "parameters": ("params", "parameters", "soil", "site", "geometry", "vegetation", "canopy", "plant", "snow", "residue", "texture"),
    "boundary_conditions": ("boundary", "control", "flags", "settings"),
}


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if len(t) > 2}


@lru_cache(maxsize=64)
def declared_inputs(ki_root: str) -> tuple[dict, ...]:
    """Every input the KI declares, flattened, with the stage tool that writes its format."""
    root = Path(ki_root)
    dag = root / "dag.yaml"
    if yaml is None or not dag.is_file():
        return ()
    try:
        doc = yaml.safe_load(dag.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — a broken dag declares nothing
        return ()
    groups = doc.get("inputs") or {}
    entries = []
    if isinstance(groups, dict):
        for category, items in groups.items():
            for it in items or []:
                if isinstance(it, dict) and it.get("name"):
                    entries.append({**it, "category": it.get("category") or category})
    elif isinstance(groups, list):
        entries = [it for it in groups if isinstance(it, dict) and it.get("name")]
    out = []
    for it in entries:
        fmt = str(it.get("model_input_format") or "")
        ext = next((m.group(0) for m in [re.search(r"\.[a-z]{2,4}", fmt)] if m), "")
        out.append({
            "name": str(it["name"]), "category": str(it.get("category") or ""),
            "unit": str(it.get("unit") or ""), "source_kind": str(it.get("source_kind") or ""),
            "format": fmt, "notes": str(it.get("notes") or ""),
            "default_tool": _format_writer(root, ext) if ext else None,
        })
    return tuple(out)


_SKIP_TOOL_PREFIXES = ("run_", "parse_", "plot_", "validate_", "preflight", "check_")


@lru_cache(maxsize=256)
def _format_writer(root: Path, ext: str) -> str | None:
    """The KI tool (relative path) that writes files with this extension, if any.

    A preparation tool mentions the extension it writes ('.moi', 'site.sit'); runners,
    parsers, plotters and validators are skipped so the default is a preparation step."""
    pattern = re.compile(re.escape(ext) + r"\b")
    for path in sorted(root.rglob("tools/*.py")):
        if path.name.startswith(_SKIP_TOOL_PREFIXES):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if pattern.search(text):
            return str(path.relative_to(root))
    return None


def match(item: dict, declared: tuple[dict, ...]) -> dict | None:
    """The declared input an inventory item stands for, or None.

    Exact name, then normalized-name overlap, then the item's category keywords."""
    if not declared:
        return None
    iid = str(item.get("id") or "")
    for d in declared:
        if d["name"] == iid:
            return d
    # Only the item's own name counts; the agent's free-text category or description
    # must not pull an item onto an unrelated declared input.
    want = _tokens(iid)
    best, score = None, 0.0
    for d in declared:
        have = _tokens(re.sub(r"\(.*?\)", "", d["name"]))     # drop the parenthetical aliases
        if not have or not want:
            continue
        overlap = len(want & have) / min(len(have), len(want))
        if overlap > score:
            best, score = d, overlap
    if best is not None and score >= 0.6:
        return best
    hits = {c for c, hints in _CATEGORY_HINTS.items() if want & set(hints)}
    if len(hits) == 1:
        cat = next(iter(hits))
        group = [d for d in declared if d["category"] == cat]
        if group:
            return {**group[0], "name": f"{cat} ({len(group)} declared inputs)", "group": True}
    return None


def classify(item: dict, declared: tuple[dict, ...], produced: set[str]) -> dict:
    """Host verdict for one item: {'group': fetch|you|run, 'how': ..., 'declared': {...}|None}."""
    delivery = item.get("delivery")
    d = match(item, declared)
    dec = None if d is None else {k: d.get(k) for k in ("name", "category", "unit", "source_kind", "format", "notes", "default_tool")}
    exact = dec if (d and d.get("name") == str(item.get("id"))) else None
    if delivery in {"served", "subset"}:
        return {"group": "fetch", "how": "clip" if delivery == "subset" else "served", "declared": exact}
    if delivery == "manual":
        return {"group": "you", "how": "manual", "declared": exact}
    if item.get("status") == "ready" or item.get("local_paths"):
        return {"group": "run", "how": "on_disk", "declared": dec}
    if str(item.get("id")) in produced:
        return {"group": "run", "how": "generated", "declared": dec}
    kind = (d or {}).get("source_kind", "")
    decision = str(item.get("decision") or "").lower()
    if decision in {"user", "provide", "you"}:
        return {"group": "you", "how": "provide", "declared": dec}
    if kind in USER_KINDS:
        if d.get("default_tool") and decision != "user":
            return {"group": "run", "how": "default", "declared": dec}
        return {"group": "you", "how": "provide", "declared": dec}
    if kind in FETCH_KINDS and not item.get("dataset_id"):
        # the KI expects a forcing/observation dataset and none is pinned yet
        return {"group": "you", "how": "choose", "declared": dec}
    if kind in RUN_KINDS or d is not None:
        return {"group": "run", "how": "default" if (d or {}).get("default_tool") else "prepared", "declared": dec}
    if item.get("needs_user") and not item.get("decision"):
        return {"group": "you", "how": "provide", "declared": dec}
    return {"group": "run", "how": "prepared", "declared": dec}


def instructions(item: dict, verdict: dict, project_rel: str = "inputs/user") -> str:
    """One sentence the user can act on, from the declaration; empty when nothing to do."""
    d = verdict.get("declared") or {}
    how = verdict.get("how")
    if how == "provide":
        bits = []
        if d.get("format"):
            bits.append(f"format {d['format']}")
        if d.get("unit"):
            bits.append(f"unit {d['unit']}")
        if d.get("notes"):
            bits.append(d["notes"])
        where = f"{project_rel}/{item.get('id')}"
        return ("Provide it yourself: " + ("; ".join(bits) + "; " if bits else "") + f"place it at {where}.")
    if how == "choose":
        return (f"The KI expects {d.get('name') or 'this input'} from a dataset "
                f"({d.get('format') or 'model format'}); none is pinned yet. Pick one in the plan.")
    if how == "default":
        return (f"KI default: {d.get('default_tool')} prepares it"
                + (f" ({d['notes']})" if d.get("notes") else "") + ". Change only if you have your own data.")
    if how == "prepared":
        return f"Prepared during the run ({d.get('source_kind') or 'KI method'})." if d else "Prepared during the run."
    return ""
