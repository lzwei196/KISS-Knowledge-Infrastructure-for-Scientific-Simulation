"""Project preparation views built from KI-owned facts.

The chat UI should not turn a model's entire interface into a form.  This
module keeps the full contract available, but folds it into a few stages that
make sense to a person preparing a scenario: source data, spatial parameters,
scientific choices, and starting conditions.

Nothing here is inferred by an LLM.  Requirements come from ``dag.yaml`` and
``docs/format_spec.yaml``; literature comes from ``docs/papers.json``.  The
agent may later explain or satisfy the contract, but it cannot silently change
it.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import papers


GROUP_LABELS = {
    "forcing": "Source data",
    "parameters": "Parameters",
    "initial_conditions": "Initial conditions",
    "boundary_conditions": "Boundary conditions",
    "files": "Required files",
}

LANES = (
    ("source_data", "Source data",
     "Weather, observations, maps, and other raw material. Add your own data or let the agent help find a suitable source."),
    ("spatial_parameters", "Spatial & grid parameters",
     "Values that must be prepared for cells, layers, reaches, basins, or other spatial units. The agent builds these from source data."),
    ("choices", "Model choices & calibration",
     "Scientific choices, defaults, and calibration values. GeoForge asks only for decisions it cannot safely make."),
    ("starting_state", "Initial & boundary conditions",
     "The state at the beginning and edges of the simulation. Defaults can be used when the KI allows them."),
)

_DECLARATION_KEYS = {
    "name", "var", "field", "file", "variable", "source_kind",
    "model_input_format", "unit", "valid_range", "default",
}
_SPATIAL_WORDS = re.compile(
    r"\b(per[ -](?:grid|cell|layer|reach|basin|hru)|each[ -](?:grid|cell|layer)|"
    r"grid[ -]?cell|spatial|raster|soil profile|soil parameter|vegetation parameter|"
    r"mesh|domain/|lat(?:itude)?/lon(?:gitude)?)\b", re.I,
)
_SPATIAL_PATH_WORDS = re.compile(
    r"(?:^|[/_.-])(dem|terrain|static|soil|landcover|map|grid|mesh|hru|basin|"
    r"reach|shapefile|spatial)(?:$|[/_.-])", re.I,
)
_CHOICE_PATH_WORDS = re.compile(
    r"(?:^|[/_.-])(parameter|params|calibration|management|control|config|option)"
    r"(?:$|[/_.-])", re.I,
)
_STATE_PATH_WORDS = re.compile(
    r"(?:^|[/_.-])(initial|boundary|restart|state|spinup|warmstart|warm-start)"
    r"(?:$|[/_.-])", re.I,
)


def _short(value, limit: int = 700) -> str:
    return " ".join(str(value or "").split())[:limit]


def _key(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _display_name(value) -> str:
    text = _short(value or "Unnamed requirement", 180)
    return text.replace("_", " ")


def flatten_declarations(value, subgroup: tuple[str, ...] = ()) -> list[dict]:
    """Return declarations from both flat and nested KI input sections.

    DSSAT, VIC, and several other KIs place parameter lists under keys such as
    ``critical`` and ``calibration``.  Treating the outer mapping as one item
    hid the actual requirements in the old UI.
    """
    out: list[dict] = []
    if isinstance(value, list):
        for item in value:
            out.extend(flatten_declarations(item, subgroup))
        return out
    if not isinstance(value, dict):
        return out
    if set(value) & _DECLARATION_KEYS and any(
            value.get(k) not in (None, "", [])
            for k in ("name", "var", "field", "file", "variable")):
        item = dict(value)
        if subgroup:
            item["subgroup"] = " / ".join(subgroup)
        return [item]
    for name, nested in value.items():
        if str(name).startswith("_"):
            continue
        out.extend(flatten_declarations(nested, subgroup + (_display_name(name),)))
    return out


def _load_format_spec(ki) -> dict:
    path = Path(ki.root) / "docs" / "format_spec.yaml"
    if not path.is_file():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _merge_fact(base: dict, extra: dict) -> dict:
    merged = dict(base)
    for field in (
        "file", "variable", "column", "unit", "format", "description",
        "notes", "valid_range", "default", "missing_value", "sensitivity",
        "conversion_from_cmfd", "model_input_format", "source_kind",
    ):
        if merged.get(field) in (None, "", []) and extra.get(field) not in (None, "", []):
            merged[field] = extra[field]
    if extra.get("subgroup") and not merged.get("subgroup"):
        merged["subgroup"] = extra["subgroup"]
    return merged


def _model_inputs(ki) -> list[dict]:
    dag = ki.dag_doc if isinstance(ki.dag_doc, dict) else {}
    dag_inputs = dag.get("inputs") if isinstance(dag.get("inputs"), dict) else {}
    spec = _load_format_spec(ki)
    spec_inputs = spec.get("inputs") if isinstance(spec.get("inputs"), dict) else {}
    requirements: list[dict] = []

    for group in ("forcing", "parameters", "initial_conditions", "boundary_conditions"):
        primary = flatten_declarations(dag_inputs.get(group) or [])
        detailed = flatten_declarations(spec_inputs.get(group) or [])
        detail_by_name = {_key(d.get("name") or d.get("var") or d.get("field")): d
                          for d in detailed}
        used: set[str] = set()
        for raw in primary:
            name = (raw.get("name") or raw.get("var") or raw.get("field") or
                    raw.get("variable") or raw.get("file"))
            name_key = _key(name)
            merged = _merge_fact(raw, detail_by_name.get(name_key, {}))
            used.add(name_key)
            requirements.append(_normalise(merged, group, ki.name))
        # The format specification often contains executable details not
        # repeated in dag.yaml (file columns, valid ranges, control files).
        for raw in detailed:
            name = (raw.get("name") or raw.get("var") or raw.get("field") or
                    raw.get("variable") or raw.get("file"))
            if _key(name) not in used:
                requirements.append(_normalise(raw, group, ki.name))

    # Concrete required files are useful, but belong under source preparation
    # rather than a new fifth checklist.
    file_section = spec_inputs.get("files") or {}
    if isinstance(file_section, dict):
        required_files = file_section.get("required") or []
    else:
        required_files = file_section
    for raw in flatten_declarations(required_files):
        requirements.append(_normalise(raw, "files", ki.name))
    return requirements


def _lane_for(group: str, fact: dict) -> str:
    if group in ("initial_conditions", "boundary_conditions"):
        return "starting_state"
    if group in ("forcing", "files"):
        return "source_data"
    text = " ".join(_short(fact.get(k), 300) for k in (
        "name", "file", "format", "model_input_format", "description", "notes",
    ))
    source = _short(fact.get("source_kind"), 100).casefold()
    if group == "parameters" and (
            _SPATIAL_WORDS.search(text) or
            source in {"dataset_lookup", "dataset", "user geological observation data"}):
        return "spatial_parameters"
    return "choices"


def _action_for(lane: str, source_kind: str) -> tuple[str, str]:
    source = source_kind.casefold()
    if lane == "choices":
        if any(word in source for word in ("calibrat", "user_choice", "user choice",
                                           "user_spec", "structural")):
            return "needs_decision", "Needs a scientific choice"
        if source == "user_provided":
            return "needs_decision", "Confirm or provide a value"
        return "agent_prepare", "Agent can start from KI defaults"
    if lane == "starting_state":
        if any(word in source for word in ("default", "derived", "warm_start")):
            return "agent_prepare", "Agent can prepare a valid starting state"
        return "provide_or_find", "Add data or ask the agent to prepare it"
    if lane == "source_data" and any(word in source for word in
                                      ("user_provided", "external_file", "observation")):
        return "provide_or_find", "Add your data or choose a public source"
    return "agent_prepare", "Agent can source, convert, or generate this"


def _normalise(raw: dict, group: str, model: str) -> dict:
    name = (raw.get("name") or raw.get("var") or raw.get("field") or
            raw.get("variable") or raw.get("file"))
    source_kind = _short(raw.get("source_kind"), 120)
    lane = _lane_for(group, {**raw, "name": name})
    action, action_label = _action_for(lane, source_kind)
    item = {
        "name": _display_name(name),
        "key": _key(name),
        "model": model,
        "group": group,
        "group_label": GROUP_LABELS.get(group, _display_name(group)),
        "lane": lane,
        "action": action,
        "action_label": action_label,
        "source_kind": source_kind,
    }
    for field in ("unit", "file", "format", "model_input_format", "description",
                  "notes", "subgroup", "default", "valid_range", "sensitivity"):
        value = raw.get(field)
        if value not in (None, "", []):
            item[field] = value if field in ("default", "valid_range") else _short(value)
    return item


def _merge_requirements(model_requirements: dict[str, list[dict]]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    priority = {"agent_prepare": 0, "provide_or_find": 1, "needs_decision": 2}
    for model, requirements in model_requirements.items():
        for item in requirements:
            key = (item["lane"], item["key"] or _key(item.get("file")))
            current = merged.get(key)
            variant = {
                "model": model,
                "unit": item.get("unit"),
                "file": item.get("file"),
                "format": item.get("format") or item.get("model_input_format"),
                "valid_range": item.get("valid_range"),
                "default": item.get("default"),
            }
            variant = {k: v for k, v in variant.items() if v not in (None, "", [])}
            if current is None:
                current = {k: v for k, v in item.items()
                           if k not in ("model", "key", "model_input_format")}
                current["models"] = [model]
                current["variants"] = [variant]
                merged[key] = current
            else:
                if model not in current["models"]:
                    current["models"].append(model)
                current["variants"].append(variant)
                if priority[item["action"]] > priority[current["action"]]:
                    current["action"] = item["action"]
                    current["action_label"] = item["action_label"]
                for field in ("description", "notes", "source_kind", "subgroup"):
                    if not current.get(field) and item.get(field):
                        current[field] = item[field]
    return list(merged.values())


def _path_lane(value: str) -> str:
    """Map an actual project input path to the same compact UI lanes."""
    if _STATE_PATH_WORDS.search(value):
        return "starting_state"
    if _CHOICE_PATH_WORDS.search(value):
        return "choices"
    if _SPATIAL_PATH_WORDS.search(value):
        return "spatial_parameters"
    return "source_data"


def _location(path: Path, project: Path, label: str) -> dict | None:
    try:
        resolved = path.expanduser().resolve()
        relative = resolved.relative_to(project.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    if not resolved.exists():
        return None
    if resolved.is_file():
        count = 1
    else:
        count = 0
        try:
            for child in resolved.rglob("*"):
                if child.is_file():
                    count += 1
                    if count >= 10_000:
                        break
        except OSError:
            pass
    return {
        "label": label,
        "relative_path": relative.as_posix() or ".",
        "kind": "file" if resolved.is_file() else "folder",
        "file_count": count,
    }


def _attach_locations(lanes: list[dict], plans: list[dict], project: Path,
                      files: list[dict],
                      role_paths: dict[str, dict[str, Path]]) -> None:
    """Attach only real, project-owned input locations to each visible lane."""
    project = project.resolve()
    by_lane: dict[str, list[dict]] = {lane["id"]: [] for lane in lanes}
    seen: dict[str, set[str]] = {lane["id"]: set() for lane in lanes}
    actual_files: dict[str, set[str]] = {lane["id"]: set() for lane in lanes}

    def track_files(lane_id: str, candidate: Path) -> None:
        try:
            resolved = candidate.expanduser().resolve()
            if resolved.is_file():
                actual_files[lane_id].add(resolved.relative_to(project).as_posix())
            elif resolved.is_dir():
                for child in resolved.rglob("*"):
                    if child.is_file():
                        actual_files[lane_id].add(
                            child.resolve().relative_to(project).as_posix())
                        if len(actual_files[lane_id]) >= 10_000:
                            break
        except (OSError, RuntimeError, ValueError):
            pass

    def add(lane_id: str, candidate: Path, label: str) -> None:
        row = _location(candidate, project, label)
        if not row or row["relative_path"] in seen[lane_id]:
            return
        seen[lane_id].add(row["relative_path"])
        by_lane[lane_id].append(row)

    # Files uploaded, downloaded, or produced under inputs are the clearest
    # representation of what belongs to this run.  Group their containing
    # folders using path names, without guessing scientific readiness.
    for item in files:
        relative = str(item.get("relative_path") or "")
        if not relative:
            continue
        lane_id = _path_lane(relative)
        target = project / relative
        track_files(lane_id, target)
        add(lane_id, target.parent, target.parent.name or "Project inputs")

    # The setup manifest provides exact checked paths.  Some legacy KIs keep a
    # runnable input deck under outputs/ or a model-specific data directory;
    # show that real location instead of insisting everything live in inputs/.
    for plan in plans:
        model = str(plan.get("model") or "KI")
        for item in plan.get("datasets") or []:
            expected = item.get("expected_path")
            if not expected:
                continue
            path = Path(str(expected)).expanduser()
            if not path.is_absolute():
                path = project / path
            lane_id = _path_lane(" ".join(str(item.get(key) or "") for key in (
                "name", "why", "expected_path")))
            track_files(lane_id, path)
            add(lane_id, path, f"{model} input")

    role_lane = {
        "forcing": "source_data", "obs": "source_data",
        "data": "source_data", "data_ki": "source_data",
        "static": "spatial_parameters",
    }
    for model, paths_by_role in role_paths.items():
        for role, path in paths_by_role.items():
            lane_id = role_lane.get(role)
            if lane_id:
                if role not in {"data", "data_ki"}:
                    track_files(lane_id, Path(path))
                add(lane_id, Path(path), f"{model} · {role}")

    inputs = project / "inputs"
    input_root = _location(inputs, project, "All project inputs")
    for lane in lanes:
        rows = by_lane[lane["id"]]
        lane["locations"] = rows[:6]
        lane["local_file_count"] = len(actual_files[lane["id"]])
    # A stable top-level escape hatch remains useful even before any files
    # exist or when a KI stores several categories in one deck.
    if input_root:
        for lane in lanes:
            lane["input_root"] = input_root


def _literature(ki, outputs: list[str]) -> dict | None:
    library = papers.load(ki)
    if library is None:
        return None
    wanted = {_key(q) for q in outputs}

    def rank(paper):
        overlap = any(any(_key(q) in wanted_name or wanted_name in _key(q)
                          for wanted_name in wanted if wanted_name)
                      for q in paper.serves)
        role = {"calibration": 0, "sensitivity": 1, "benchmark": 2,
                "threshold_convention": 3, "supporting": 4}.get(paper.role, 5)
        return (not overlap, role, not paper.open_access, paper.title.casefold())

    selected = sorted(library.papers, key=rank)[:4]
    return {
        "model": ki.name,
        "count": len(library.papers),
        "open_access": len(library.open_papers),
        "recommended": [p.as_dict() | {"url": p.url} for p in selected],
    }


def build(kis: list, plans: list[dict], project: Path, files: list[dict],
          *, auto_ki: bool = False,
          role_paths: dict[str, dict[str, Path]] | None = None) -> dict:
    """Build the compact, multi-model project preparation contract."""
    requirements = {ki.name: _model_inputs(ki) for ki in kis}
    combined = _merge_requirements(requirements)
    lanes = []
    for lane_id, label, description in LANES:
        items = [item for item in combined if item["lane"] == lane_id]
        items.sort(key=lambda item: (
            {"needs_decision": 0, "provide_or_find": 1, "agent_prepare": 2}.get(
                item["action"], 3), item["name"].casefold()))
        lanes.append({
            "id": lane_id,
            "label": label,
            "description": description,
            "count": len(items),
            "needs_user": sum(item["action"] != "agent_prepare" for item in items),
            "agent_can_prepare": sum(item["action"] == "agent_prepare" for item in items),
            "items": items[:350],
        })

    _attach_locations(lanes, plans, Path(project), files, role_paths or {})

    plan_by_model = {p.get("model"): p for p in plans}
    models = []
    for ki in kis:
        plan = plan_by_model.get(ki.name, {})
        counts = {lane["id"]: sum(r["lane"] == lane["id"]
                                  for r in requirements.get(ki.name, [])) for lane in lanes}
        models.append({
            "name": ki.name,
            "software": plan.get("software") or {},
            "counts": counts,
            "outputs": plan.get("outputs") or [],
        })

    software_ready = sum(bool(m["software"].get("can_run")) for m in models)
    if auto_ki:
        readiness = {"state": "ready", "label": "Ready for the agent",
                     "detail": "GeoForge will choose a suitable KI from the scenario and prepare its inputs."}
    elif not files:
        readiness = {"state": "ready", "label": "Ready for the agent",
                     "detail": "The agent will inspect the KI, locate usable sources, and prepare the model inputs."}
    else:
        readiness = {"state": "validate_sources", "label": "Validate added data",
                     "detail": "Files are present. Ask the agent to map, inspect, and convert them for the selected KIs."}

    literature = []
    literature_missing = []
    for ki in kis:
        output_names = [str(o.get("name", "")) for o in plan_by_model.get(ki.name, {}).get("outputs", [])]
        row = _literature(ki, output_names)
        if row:
            literature.append(row)
        else:
            literature_missing.append(ki.name)

    names = ", ".join(ki.name for ki in kis) or "the most suitable KI"
    agent_prompt = (
        f"Prepare this GeoForge project for {names}. Continue from the scenario already "
        "described in our conversation; do not make me repeat information you can infer. "
        "Inspect the project and the KI, then actually create the required inputs using "
        "KI defaults, suitable public sources, and the shipped KI preparation tools. "
        "Do not enumerate the raw input contract or give me a long setup plan. Ask only "
        "if you are blocked by one missing scenario boundary, a high-impact scientific "
        "choice, or private/licensed data. Group any questions into one short message. "
        "Validate the prepared inputs before running the model."
    )
    return {
        "generated_by_ai": False,
        "active": bool(kis),
        "sources": ["dag.yaml", "docs/format_spec.yaml", "docs/papers.json"],
        "project_readiness": readiness,
        "software_summary": {
            "ready": software_ready,
            "total": len(models),
            "note": "Software verification is separate from project data readiness.",
        },
        "models": models,
        "lanes": lanes,
        "literature": literature,
        "literature_missing": literature_missing,
        "paper_note": papers.SCHEMA_NOTE,
        "references_path": str(project / "references" / "papers"),
        "agent_prompt": agent_prompt,
    }
