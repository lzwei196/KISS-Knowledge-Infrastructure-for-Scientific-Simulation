"""flow.plan — derive the first plan from the KIs' own files, validate the agent's plan, hash it.

Plan v3 map A3. `build_indexes`, `UNNAMED_PATTERNS`, `_strategy_for_canonical`,
`_pick_forcing_provider`, `_strategy_for_unnamed`, `derive_plan_for_model`,
`emit_coupling_graph` and `derive_full_plan` are ADOPTED from
ata-kdt/planner/derive_plan.py (L61-179, 182-216, 219-326, 328-358, 360-380,
382-436, 438-509, 511-565) — the same deterministic planner chat runs before its
agent starts (pre_planner.py). Two changes only:
  * the hardcoded ROOT/ATA_DIR/DATA_KI_DIR/COUPLINGS_DIR (L50-53) became `DataRoots`,
    so the desktop can point at its bundled copy of cards/couplings/forcing_providers;
  * the `_dispatch_subagent` observation stub (L542) is gone — observations are an
    inventory item like any other input.

`to_artifacts()` maps the derived plan onto the two files the issue requires
(`runs/plan.json`, `runs/data-inventory.json`, schema_version "1.0");
`validate()` checks what the agent wrote back; `sha256()` is canonical.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "1.0"

# The two artifacts the issue requires (ANALYSIS/01_DESKTOP_ISSUE.md "Planning Gate 的强制产物").
# Kept as plain required-key maps so the frozen desktop needs no jsonschema dependency.
PLAN_SCHEMA = {
    "required": ("schema_version", "goal", "selected_kis", "steps", "scientific_choices",
                 "unresolved_questions", "created_at"),
    "step_required": ("id", "ki", "tool", "inputs", "outputs", "status"),
    "step_status": ("planned", "running", "done", "failed", "skipped"),
    "choice_required": ("id", "kind", "high_impact"),
}
INVENTORY_SCHEMA = {
    "required": ("schema_version", "items"),
    "item_required": ("id", "required_by", "status", "acceptable_sources", "chosen_source",
                      "local_paths", "agent_resolvable", "needs_user"),
    "item_status": ("missing", "resolved", "ready"),
}


_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_ENV_BLOCKED_EXACT = {
    "HOME", "PATH", "SHELL", "USER", "LOGNAME", "TMPDIR",
    "KISS_ROOT",
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT",
    "BASH_ENV", "ENV", "NODE_OPTIONS", "RUBYOPT", "PERL5OPT", "PERL5LIB",
}
_ENV_SECRET_FRAGMENTS = (
    "API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH",
)
_ENV_ALLOWED_TOKENS = {"PROJECT", "KI_ROOT"}


def validate_step_environment(value: Any) -> list[str]:
    """Validate an optional, approval-bound step environment.

    These values configure a shipped KI tool; they are not a second command
    language. In particular, a plan cannot alter executable search paths,
    inject interpreter startup code, or carry credentials.
    """
    if value is None:
        return []
    if not isinstance(value, dict):
        return ["env must be an object of string keys and values"]
    errors: list[str] = []
    if len(value) > 128:
        errors.append("env may contain at most 128 entries")
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        upper = key.upper()
        if not _ENV_KEY_RE.fullmatch(key):
            errors.append(f"env key {key!r} is invalid")
            continue
        if (upper in _ENV_BLOCKED_EXACT or upper.startswith(("LD_", "DYLD_", "GEOFORGE_")) or
                any(fragment in upper for fragment in _ENV_SECRET_FRAGMENTS)):
            errors.append(f"env key {key!r} is not allowed")
        if not isinstance(raw_value, str):
            errors.append(f"env value for {key!r} must be a string")
            continue
        if len(raw_value) > 8192 or "\x00" in raw_value:
            errors.append(f"env value for {key!r} is too long or contains NUL")
        tokens = set(re.findall(r"\$\{([^}]+)\}", raw_value))
        unknown = sorted(tokens - _ENV_ALLOWED_TOKENS)
        if unknown:
            errors.append(f"env value for {key!r} uses unsupported tokens {unknown}")
    return errors


def step_environment(step: dict, project: Path, ki_root: Path) -> dict[str, str]:
    """Expand the already-approved environment for one plan step.

    Only two literal tokens are expanded. Absolute path values must remain
    inside the chat project or selected KI so an approved environment cannot
    become a write channel into arbitrary user/system locations.
    """
    raw = step.get("env")
    errors = validate_step_environment(raw)
    if errors:
        raise ValueError("; ".join(errors))
    if not raw:
        return {}
    project = Path(project).resolve()
    ki_root = Path(ki_root).resolve()
    result: dict[str, str] = {}
    for key, value in raw.items():
        expanded = value.replace("${PROJECT}", str(project)).replace("${KI_ROOT}", str(ki_root))
        candidate = Path(expanded).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve(strict=False)
            if not any(resolved == base or base in resolved.parents for base in (project, ki_root)):
                raise ValueError(f"env path for {key!r} is outside the project and KI")
        result[key] = expanded
    return result


@dataclass(frozen=True)
class DataRoots:
    """Where the planner's data lives. Server default = the real ata-kdt tree."""
    root: Path                      # for relative card_path strings
    cards: Path                     # *_ata_card.yaml
    couplings: Path                 # coupling_config_*.yaml + couple_*.py
    forcing_providers: Path         # cmfd.yaml, mswx.yaml, ...
    data_ki: Path | None = None     # data_ki/<X>/card.yaml (none exist today → falls through)
    coupling_matrix: Path | None = None  # artifacts/coupling_matrix_v2.yaml (optional)

    @classmethod
    def server(cls, root: str | Path = "/mnt/disk1/Hydrocraft_server") -> "DataRoots":
        r = Path(root)
        return cls(root=r, cards=r / "ata-kdt" / "cards", couplings=r / "ata-kdt" / "couplings",
                   forcing_providers=r / "ata-kdt" / "forcing_providers", data_ki=r / "data_ki",
                   coupling_matrix=r / "ata-kdt" / "artifacts" / "coupling_matrix_v2.yaml")

    @classmethod
    def bundled(cls, data_dir: str | Path) -> "DataRoots":
        """The desktop's flow/data/ copy (plan v3 A8)."""
        d = Path(data_dir)
        return cls(root=d, cards=d / "cards", couplings=d / "couplings",
                   forcing_providers=d / "forcing_providers", data_ki=d / "data_ki",
                   coupling_matrix=d / "coupling_matrix_v2.yaml")


def _rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------------------
# Index construction — derive_plan.py L61-179, verbatim except for the roots
# ---------------------------------------------------------------------------

def build_indexes(roots: DataRoots) -> dict:
    """Build the indexes the derive function joins against."""
    forcing_index: dict[str, list[dict]] = defaultdict(list)
    dataset_index: dict[str, list[dict]] = defaultdict(list)
    coupling_index: dict[str, list[dict]] = defaultdict(list)
    canonical_registry: set[str] = set()

    # 1. forcing_providers/*.yaml — canonical_id → provider list
    for f in sorted(roots.forcing_providers.glob("*.yaml")):
        try:
            d = yaml.safe_load(f.read_text())
        except Exception:
            continue
        pid = d.get("provider_id") or f.stem
        for var in (d.get("variables") or []):
            cid = var.get("canonical_id")
            if cid:
                forcing_index[cid].append({
                    "provider_id": pid,
                    "name": d.get("provider_name", pid),
                    "data_path": d.get("data_path"),
                    "card_path": _rel(f, roots.root),
                    "native_unit": var.get("unit"),
                })
                canonical_registry.add(cid)

    # 2. data_ki/<X>/card.yaml — canonical_id → dataset lookup list
    if roots.data_ki and roots.data_ki.is_dir():
        for f in sorted(roots.data_ki.glob("*/card.yaml")):
            try:
                d = yaml.safe_load(f.read_text())
            except Exception:
                continue
            ident = d.get("identity", {})
            ds_id = ident.get("dataset_id") or f.parent.name
            lookup = d.get("lookup", {}) or {}
            coverage = d.get("coverage", {}) or {}
            for var in (d.get("variables") or []):
                cid = var.get("canonical_id")
                if cid:
                    dataset_index[cid].append({
                        "dataset_id": ds_id,
                        "lookup_module": lookup.get("module"),
                        "lookup_function": lookup.get("function", "lookup"),
                        "lookup_signature": lookup.get("signature", {}),
                        "spatial_coverage": coverage.get("spatial"),
                        "bounds": coverage.get("bounds"),
                        "native_unit": var.get("unit"),
                        "card_path": _rel(f, roots.root),
                    })
                    canonical_registry.add(cid)

    # 3. cards/*_ata_card.yaml — canonical_id → producer model list
    for f in sorted(roots.cards.glob("*_ata_card.yaml")):
        try:
            d = yaml.safe_load(f.read_text())
        except Exception:
            continue
        m = d.get("identity", {}).get("model_id") or f.stem.replace("_ata_card", "")
        for o in (d.get("outputs") or []):
            cid = o.get("canonical_id")
            if cid:
                origin = o.get("origin", "")
                # Only count actual simulation outputs as producers — not echoed inputs.
                if origin in ("simulated", ""):
                    coupling_index[cid].append({
                        "model_id": m,
                        "local_name": o.get("local_name"),
                        "unit": o.get("unit"),
                    })
                    canonical_registry.add(cid)

    # 4. Pre-built coupling configs — directory listing of couplings/.
    prebuilt_couplings: dict[tuple[str, str], dict] = {}
    if roots.couplings.exists():
        for yml in roots.couplings.glob("coupling_config_*.yaml"):
            stem = yml.stem.replace("coupling_config_", "")
            if "_to_" in stem:
                src, tgt = stem.split("_to_", 1)
                py = roots.couplings / f"couple_{src}_to_{tgt}.py"
                prebuilt_couplings[(src, tgt)] = {
                    "config_path": _rel(yml, roots.root),
                    "wrapper_path": _rel(py, roots.root) if py.exists() else None,
                }

    # 5. Coupling matrix v2 — optional edge metadata
    coupling_matrix: dict[tuple[str, str], dict] = {}
    matrix_file = roots.coupling_matrix
    if matrix_file and matrix_file.exists():
        try:
            mat = yaml.safe_load(matrix_file.read_text())
            for etype, info in (mat.get("edge_types") or {}).items():
                for ex in (info.get("examples") or []):
                    edge = ex.get("edge", "")
                    if " -> " in edge:
                        src, tgt = edge.split(" -> ", 1)
                        coupling_matrix[(src.strip(), tgt.strip())] = {
                            "edge_type": etype,
                            "shared_vars": ex.get("shared_vars", []),
                            "n_shared": ex.get("n_shared"),
                        }
        except Exception:
            pass

    return {
        "forcing": dict(forcing_index),
        "dataset": dict(dataset_index),
        "coupling": dict(coupling_index),
        "prebuilt_couplings": prebuilt_couplings,
        "coupling_matrix": coupling_matrix,
        "canonical_registry": canonical_registry,
    }


# ---------------------------------------------------------------------------
# Per-input strategy resolver — derive_plan.py L182-380, verbatim
# ---------------------------------------------------------------------------

UNNAMED_PATTERNS = [
    (r"basin.*shp|domain|shapefile|extent", {
        "kind": "from_basin_probe",
        "fallback": [{"kind": "from_user"}],
    }),
    (r"period|year|start.*end|simulation.*time", {
        "kind": "from_user_message.year_range",
        "fallback": [{"kind": "default", "value": {"start_year": 2000, "end_year": 2010}}],
    }),
    (r"location|lat.*lon|coord", {
        "kind": "from_user_message.place_name",
        "fallback": [
            {"kind": "from_user_message.coords"},
            {"kind": "from_user"},
        ],
    }),
    (r"crop|cultivar", {
        "kind": "from_user_message.crop",
        "fallback": [{"kind": "from_user"}],
    }),
    (r"resolution|grid.*size|dx", {
        "kind": "derived",
        "rule": "resolution_from_area",
        "fallback": [{"kind": "default", "value": 0.25}],
    }),
    (r"routing|method|scheme", {
        "kind": "intent_keywords",
        "fallback": [{"kind": "from_user"}],
    }),
    (r"observ|gauge|station", {
        "kind": "from_station_search",
        "fallback": [{"kind": "from_user"}],
    }),
]


def _strategy_for_canonical(cid: str, input_category: str, indexes: dict, intent: dict) -> dict:
    """Pick the best strategy for a canonical input."""
    upstream_options = []
    other_models = [m for m in intent.get("models", []) if m != intent.get("_current_model")]
    for prod in indexes["coupling"].get(cid, []):
        if prod["model_id"] in other_models:
            upstream_options.append(prod)

    dataset_options = indexes["dataset"].get(cid, [])
    forcing_options = indexes["forcing"].get(cid, [])

    if intent.get("lat") is not None and intent.get("lon") is not None:
        lat, lon = intent["lat"], intent["lon"]
        in_china = 70 <= lon <= 140 and 15 <= lat <= 55

        def _cov_score(opt):
            cov = opt.get("spatial_coverage")
            if cov == "global":
                return 0
            if cov == "china" and in_china:
                return 1
            if cov == "regional":
                return 2
            return 3
        dataset_options = sorted(dataset_options, key=_cov_score)

    primary = None
    fallbacks: list[dict] = []

    # Precedence: upstream model in run → dataset lookup → forcing provider → ask user
    if upstream_options:
        src = upstream_options[0]["model_id"]
        tgt = intent.get("_current_model")
        prebuilt = indexes["prebuilt_couplings"].get((src, tgt))
        edge_meta = indexes["coupling_matrix"].get((src, tgt))
        primary = {
            "kind": "from_upstream_model",
            "upstream_model": src,
            "upstream_local_name": upstream_options[0].get("local_name"),
            "upstream_unit": upstream_options[0].get("unit"),
            "rationale": f"{src} is in the run and outputs {cid}",
            "prebuilt_coupling_config": prebuilt["config_path"] if prebuilt else None,
            "prebuilt_python_wrapper": prebuilt["wrapper_path"] if prebuilt else None,
            "needs_pipeline2_gen": prebuilt is None,
            "edge_type": edge_meta.get("edge_type") if edge_meta else None,
        }
        for opt in upstream_options[1:]:
            fallbacks.append({"kind": "from_upstream_model", "upstream_model": opt["model_id"]})

    if dataset_options:
        ds = {
            "kind": "from_dataset_lookup",
            "dataset": dataset_options[0]["dataset_id"],
            "lookup_module": dataset_options[0]["lookup_module"],
            "lookup_signature": dataset_options[0]["lookup_signature"],
            "native_unit": dataset_options[0]["native_unit"],
            "spatial_coverage": dataset_options[0]["spatial_coverage"],
        }
        if primary is None:
            primary = ds
        else:
            fallbacks.append(ds)
        for opt in dataset_options[1:]:
            fallbacks.append({
                "kind": "from_dataset_lookup",
                "dataset": opt["dataset_id"],
                "lookup_module": opt["lookup_module"],
            })

    if forcing_options and input_category == "forcing":
        provider_pick = _pick_forcing_provider(forcing_options, intent)
        fp = {
            "kind": "from_forcing_provider",
            "picked_provider": provider_pick,
            "all_options": [o["provider_id"] for o in forcing_options],
            "pick_rule": "by_location_and_period",
            "rationale": f"location/period rule picks {provider_pick}",
        }
        if primary is None:
            primary = fp
        else:
            fallbacks.append(fp)

    if primary is None:
        primary = {
            "kind": "from_user",
            "rationale": (
                f"No producer in run, no data_ki lookup, no forcing provider for "
                f"canonical_id={cid}. User must supply."
            ),
        }

    return {"primary": primary, "fallback": fallbacks}


def _pick_forcing_provider(options: list[dict], intent: dict) -> str:
    """Location+period rule: CMFD in China ≤2018 → MSWX → NASA POWER → ERA5 (chat's
    LOCATION AWARENESS rule, made deterministic)."""
    lat, lon = intent.get("lat"), intent.get("lon")
    start_year = intent.get("start_year")
    end_year = intent.get("end_year")
    pids = {o["provider_id"]: o for o in options}
    in_china = lat is not None and lon is not None and 70 <= lon <= 140 and 15 <= lat <= 55
    if "cmfd_v1" in pids and in_china:
        if start_year is None or (start_year >= 1979 and (end_year or 2018) <= 2018):
            return "cmfd_v1"
    if "mswx_v1" in pids:
        if start_year is None or (start_year >= 1979 and (end_year or 2026) <= 2026):
            return "mswx_v1"
    if "nasa_power_v1" in pids:
        return "nasa_power_v1"
    if "era5_v1" in pids:
        return "era5_v1"
    return options[0]["provider_id"]


def _strategy_for_unnamed(local_name: str, input_category: str, intent: dict) -> dict:
    """Heuristic strategy for inputs without canonical_id."""
    n = (local_name or "").lower()
    for pattern, tmpl in UNNAMED_PATTERNS:
        if re.search(pattern, n):
            return {"primary": dict(tmpl), "fallback": tmpl.get("fallback", [])}
    return {
        "primary": {
            "kind": "from_user",
            "rationale": f"local_name={local_name!r} did not match any known pattern; "
                         f"treated as model-specific config.",
        },
        "fallback": [],
    }


# ---------------------------------------------------------------------------
# Plan derivation — derive_plan.py L382-565
# ---------------------------------------------------------------------------

def derive_plan_for_model(model_id: str, intent: dict, indexes: dict, roots: DataRoots) -> dict:
    card_path = roots.cards / f"{model_id}_ata_card.yaml"
    if not card_path.exists():
        return {"model": model_id, "error": f"ATA card not found: {card_path}",
                "inputs": [], "ask_user": [], "input_count": 0, "auto_resolved": 0}
    card = yaml.safe_load(card_path.read_text())
    intent_with_self = {**intent, "_current_model": model_id}
    inputs_plan, ask_user = [], []
    for inp in (card.get("inputs") or []):
        cid = inp.get("canonical_id")
        local_name = inp.get("local_name") or ""
        category = inp.get("input_category") or "?"
        unit = inp.get("unit") or ""
        if cid:
            strategy = _strategy_for_canonical(cid, category, indexes, intent_with_self)
        else:
            strategy = _strategy_for_unnamed(local_name, category, intent_with_self)
        inputs_plan.append({
            "canonical_id": cid, "local_name": local_name, "input_category": category,
            "unit": unit, "primary_strategy": strategy["primary"], "fallbacks": strategy["fallback"],
        })
        if strategy["primary"]["kind"] == "from_user":
            ask_user.append({"field": local_name or cid or "<unnamed>", "category": category,
                             "unit": unit, "rationale": strategy["primary"].get("rationale")})
    return {"model": model_id, "card_path": _rel(card_path, roots.root), "inputs": inputs_plan,
            "ask_user": ask_user, "input_count": len(inputs_plan),
            "auto_resolved": len(inputs_plan) - len(ask_user)}


def emit_coupling_graph(plan: dict, output_path: Path) -> None:
    """Abstract coupling_graph.yaml (derive_plan.py L438-509); run-concrete node fields are
    left for the execution turn, exactly as chat's run_model expects."""
    edges, data_lookups, forcing_provider, seen = [], [], None, set()
    for mp in plan.get("plans", []):
        target = mp["model"]
        for inp in mp.get("inputs", []):
            ps = inp.get("primary_strategy", {})
            kind = ps.get("kind")
            if kind == "from_upstream_model":
                source = ps["upstream_model"]
                if (source, target) in seen:
                    continue
                seen.add((source, target))
                edges.append({
                    "source": source, "target": target, "edge_id": f"{source}_to_{target}",
                    "edge_type": ps.get("edge_type"),
                    "variables": [inp.get("canonical_id")] if inp.get("canonical_id") else [],
                    "prebuilt_config": ps.get("prebuilt_coupling_config"),
                    "prebuilt_wrapper": ps.get("prebuilt_python_wrapper"),
                    "needs_pipeline2_gen": ps.get("needs_pipeline2_gen", False),
                })
            elif kind == "from_dataset_lookup":
                data_lookups.append({"model": target,
                                     "input": inp.get("local_name") or inp.get("canonical_id"),
                                     "dataset": ps.get("dataset"),
                                     "lookup_module": ps.get("lookup_module"),
                                     "args_template": "lat,lon/per_grid_cell"})
            elif kind == "from_forcing_provider" and forcing_provider is None:
                forcing_provider = ps.get("picked_provider")
    out = {
        "coupling_graph_version": "1.0",
        "generated_by": "ki_tools_common.flow.plan (port of ata-kdt/planner/derive_plan.py)",
        "intent": plan.get("intent", {}), "models": plan.get("models", []),
        "forcing_provider": forcing_provider, "edges": edges, "data_lookups": data_lookups,
        "ask_user": plan.get("ask_user_combined", []), "summary": plan.get("summary", {}),
        "_TODO_for_agent": ("Before running dag_orchestrator.py, fill in per-node "
                            "{execute_command, working_dir, expected_outputs} in a new 'nodes' "
                            "section that mirrors ata-kdt/ten_cases/case*/coupling_graph.yaml"),
        "_TODO_for_execution": ("the above is done in the EXECUTING turn, never in planning"),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(out, default_flow_style=False, sort_keys=False))


def derive_full_plan(models: list[str], intent: dict, roots: DataRoots,
                     indexes: dict | None = None) -> dict:
    if indexes is None:
        indexes = build_indexes(roots)
    intent_full = {**intent, "models": models}
    plans = [derive_plan_for_model(m, intent_full, indexes, roots) for m in models]
    seen, combined = set(), []
    for p in plans:
        for q in p.get("ask_user", []):
            key = (q["field"], q["category"])
            if key in seen:
                continue
            seen.add(key)
            combined.append(q)
    total_inputs = sum(p.get("input_count", 0) for p in plans)
    total_resolved = sum(p.get("auto_resolved", 0) for p in plans)
    return {
        "models": models, "intent": intent, "plans": plans, "ask_user_combined": combined,
        "summary": {"models": len(models), "total_inputs": total_inputs,
                    "auto_resolved": total_resolved, "asked_of_user": len(combined),
                    "auto_resolution_rate": round(total_resolved / total_inputs, 3) if total_inputs else 0.0},
    }


# ---------------------------------------------------------------------------
# The two artifacts the issue requires
# ---------------------------------------------------------------------------

HIGH_IMPACT_CHOICES = ("forcing_source", "licence", "login", "private_data",
                       "calibration_target", "spatial_extent", "period", "scenario")


def _dag_steps(model_id: str, ki_root: Path | None) -> list[dict]:
    """Ordered steps from the KI's dag.yaml `processes` (tool left null for the agent to
    fill from the KI's tools/; validate() checks it). Falls back to one 'run' step."""
    steps: list[dict] = []
    dag = None
    if ki_root:
        p = Path(ki_root) / "dag.yaml"
        if p.is_file():
            try:
                dag = yaml.safe_load(p.read_text(errors="ignore")) or {}
            except Exception:
                dag = None
    procs = (dag or {}).get("processes") or []
    if isinstance(procs, dict):
        # KDT dag.yaml: processes = {modules: [...], internal_edges: [...]}; the modules are the steps
        if isinstance(procs.get("modules"), list):
            procs = procs["modules"]
        else:
            procs = [{"id": k, **(v if isinstance(v, dict) else {})} for k, v in procs.items()]
    for i, pr in enumerate(procs):
        if not isinstance(pr, dict):
            continue
        pid = str(pr.get("id") or pr.get("name") or f"step_{i+1}")
        steps.append({"id": f"{model_id}:{pid}", "ki": model_id, "tool": None,
                      "kind": "process", "inputs": [str(x) for x in (pr.get("inputs") or [])][:20],
                      "outputs": [str(x) for x in (pr.get("outputs") or [])][:20],
                      "status": "planned"})
    if not steps:
        steps.append({"id": f"{model_id}:run", "ki": model_id, "tool": None, "kind": "run",
                      "inputs": [], "outputs": [], "status": "planned"})
    return steps


def to_artifacts(full_plan: dict, goal: str, ki_roots: dict[str, Path] | None = None,
                 edges: list[dict] | None = None) -> tuple[dict, dict]:
    """Map a derived plan onto (plan.json, data-inventory.json)."""
    ki_roots = ki_roots or {}
    items: list[dict] = []
    seen_ids: set[str] = set()
    choices: list[dict] = []
    for mp in full_plan.get("plans", []):
        model = mp["model"]
        for inp in mp.get("inputs", []):
            iid = inp.get("canonical_id") or inp.get("local_name") or "unnamed"
            ps = inp.get("primary_strategy") or {}
            kind = ps.get("kind", "from_user")
            needs_user = kind == "from_user"
            sources = []
            if kind == "from_forcing_provider":
                sources = list(ps.get("all_options") or [])
                if len(sources) > 1:
                    choices.append({"id": f"forcing_source:{iid}", "kind": "forcing_source",
                                    "options": sources, "picked": ps.get("picked_provider"),
                                    "high_impact": True, "required_by": [model]})
            elif kind == "from_dataset_lookup":
                sources = [ps.get("dataset")] + [f.get("dataset") for f in inp.get("fallbacks", [])
                                                 if f.get("kind") == "from_dataset_lookup"]
            elif kind == "from_upstream_model":
                sources = [f"model:{ps.get('upstream_model')}"]
            if iid in seen_ids:
                for it in items:
                    if it["id"] == iid and model not in it["required_by"]:
                        it["required_by"].append(model)
                continue
            seen_ids.add(iid)
            items.append({
                "id": iid, "required_by": [model], "category": inp.get("input_category"),
                "unit": inp.get("unit"),
                # 'resolved' = a source is known (forcing provider / dataset / upstream model) but
                # no file exists yet; 'missing' = nobody knows where it comes from; 'ready' is set
                # only when local_paths exist on disk (validate() enforces that)
                "status": "missing" if needs_user else "resolved",
                "strategy": kind,
                "acceptable_sources": [s for s in sources if s],
                "chosen_source": (ps.get("picked_provider") or ps.get("dataset")
                                  or ps.get("upstream_model")),
                "local_paths": [],
                "agent_resolvable": not needs_user,
                "needs_user": needs_user,
                "rationale": ps.get("rationale"),
            })
    steps: list[dict] = []
    for model in full_plan.get("models", []):
        steps.extend(_dag_steps(model, ki_roots.get(model)))
    coupling = [{"from": f"{e['source']}.{(e.get('variables') or ['output'])[0]}",
                 "to": f"{e['target']}.{(e.get('variables') or ['input'])[0]}",
                 "edge_id": e.get("edge_id"), "config_path": e.get("config_path")}
                for e in (edges or [])]
    plan_json = {
        "schema_version": SCHEMA_VERSION,
        "goal": goal,
        "selected_kis": list(full_plan.get("models", [])),
        "coupling": coupling,
        "intent": full_plan.get("intent", {}),
        "steps": steps,
        "scientific_choices": choices,
        "unresolved_questions": [q.get("field") for q in full_plan.get("ask_user_combined", [])],
        "summary": full_plan.get("summary", {}),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    inventory = {"schema_version": SCHEMA_VERSION, "items": items}
    return plan_json, inventory


def derive(models: list[str], intent: dict, goal: str, roots: DataRoots,
           ki_roots: dict[str, Path] | None = None) -> tuple[dict, dict, dict]:
    """One call: derived plan + the two artifacts. Pure; the driver caches/writes."""
    from .resolve import couplings_for
    full = derive_full_plan(models, intent, roots)
    edges = couplings_for(models, roots.couplings)
    plan_json, inventory = to_artifacts(full, goal, ki_roots, edges)
    return full, plan_json, inventory


# ---------------------------------------------------------------------------
# Validation of what the agent wrote back, and hashing
# ---------------------------------------------------------------------------

def sha256(obj: Any) -> str:
    data = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def validate(plan: dict, inventory: dict, selected_kis: list[str],
             ki_roots: dict[str, Path] | None = None, *, for_execution: bool = False) -> list[str]:
    """Return a list of problems (empty = valid). Plan v3 A3 rules.

    for_execution=True (kimi #10): the readiness check run at approval time — every
    executable step must name a tool (planning may leave it null), and every inventory item
    a step consumes must be 'resolved' or 'ready' (or carry a user decision)."""
    ki_roots = ki_roots or {}
    errs: list[str] = []
    if not isinstance(plan, dict) or not isinstance(inventory, dict):
        return ["plan.json and data-inventory.json must be JSON objects"]
    if plan.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"plan.json schema_version must be {SCHEMA_VERSION!r}")
    if inventory.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"data-inventory.json schema_version must be {SCHEMA_VERSION!r}")
    for k in PLAN_SCHEMA["required"]:
        if k not in plan:
            errs.append(f"plan.json is missing required key {k!r}")
    for k in INVENTORY_SCHEMA["required"]:
        if k not in inventory:
            errs.append(f"data-inventory.json is missing required key {k!r}")
    # Agent-authored JSON is untrusted structured input. Report schema errors
    # instead of raising TypeError and losing the planning repair handoff.
    for key in ("selected_kis", "steps", "scientific_choices", "unresolved_questions", "coupling"):
        if key in plan and not isinstance(plan[key], list):
            errs.append(f"plan.{key} must be an array")
    if not isinstance(inventory.get("items", []), list):
        errs.append("data-inventory.items must be an array")
    if errs:
        return errs
    if any(not isinstance(k, str) for k in plan.get("selected_kis", [])):
        return ["plan.selected_kis must contain KI names as strings"]
    sel = set(selected_kis)
    pk = set(plan.get("selected_kis") or [])
    if pk != sel:
        errs.append(f"plan.selected_kis {sorted(pk)} != resolved KIs {sorted(sel)}")
    items = inventory.get("items") or []
    item_ids = {str(it.get("id")) for it in items if isinstance(it, dict)}
    seen_items, seen_steps = set(), set()
    for it in items:
        if not isinstance(it, dict):
            errs.append("inventory item is not an object"); continue
        item_id = it.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in seen_items:
            errs.append("inventory item IDs must be nonempty, unique strings")
        else:
            seen_items.add(item_id)
        for key in ("required_by", "local_paths"):
            if key in it and (not isinstance(it[key], list) or any(not isinstance(v, str) for v in it[key])):
                errs.append(f"inventory item {item_id!r} {key} must be an array of strings")
        for key in ("needs_user", "agent_resolvable"):
            if key in it and not isinstance(it[key], bool):
                errs.append(f"inventory item {item_id!r} {key} must be true/false")
        if it.get("status") not in INVENTORY_SCHEMA["item_status"]:
            errs.append(f"inventory item {it.get('id')!r} has unknown status {it.get('status')!r}")
        if it.get("needs_user") and it.get("status") in ("resolved", "ready") and not it.get("decision"):
            errs.append(f"inventory item {it.get('id')!r} needs the user but is marked resolved "
                        f"with no decision")
        if it.get("status") == "ready" and not it.get("local_paths"):
            errs.append(f"inventory item {it.get('id')!r} is 'ready' but names no local file")
    steps = [s for s in (plan.get("steps") or [])]
    for idx, st in enumerate(steps):
        if not isinstance(st, dict):
            errs.append("plan step is not an object"); continue
        step_id = st.get("id")
        if not isinstance(step_id, str) or not step_id or step_id in seen_steps:
            errs.append("step IDs must be nonempty, unique strings")
        else:
            seen_steps.add(step_id)
        for k in PLAN_SCHEMA["step_required"]:
            if k not in st:
                errs.append(f"step {st.get('id')!r} is missing key {k!r}")
        if st.get("status", "planned") not in PLAN_SCHEMA["step_status"]:
            errs.append(f"step {st.get('id')!r} has unknown status {st.get('status')!r}")
        ki = st.get("ki")
        if not isinstance(ki, str):
            errs.append(f"step {st.get('id')!r} ki must be a string"); continue
        if ki not in sel:
            errs.append(f"step {st.get('id')!r} names KI {ki!r} which is not selected")
        tool = st.get("tool")
        if tool is not None and not isinstance(tool, str):
            errs.append(f"step {st.get('id')!r} tool must be a path string or null"); continue
        for problem in validate_step_environment(st.get("env")):
            errs.append(f"step {st.get('id')!r} {problem}")
        if any(not isinstance(st.get(k), list) or
               any(not isinstance(v, str) for v in st[k]) for k in ("inputs", "outputs")):
            errs.append(f"step {st.get('id')!r} inputs and outputs must be arrays of strings"); continue
        if for_execution and not tool and (st.get("kind") or "process") in (
                "process", "run", "model_run", "calibrate", "route", "couple", "prepare"):
            errs.append(f"step {st.get('id')!r} has no tool — not ready to execute")
        if for_execution:
            by_id = {str(it.get("id")): it for it in items if isinstance(it, dict)}
            # An input produced by an earlier step of this plan is not a gap:
            # the pipeline itself creates it before the consumer runs.
            produced_earlier = {str(o) for prev in steps[:idx]
                                if isinstance(prev, dict) for o in prev.get("outputs") or []}
            for inp in st.get("inputs") or []:
                it = by_id.get(str(inp))
                if (it and it.get("status") == "missing" and not it.get("decision")
                        and str(inp) not in produced_earlier):
                    errs.append(f"step {st.get('id')!r} input {inp!r} is still missing")
        if tool:
            root = ki_roots.get(ki)
            if root is None:
                errs.append(f"step {st.get('id')!r}: cannot check tool {tool!r} — no KI root for {ki!r}")
            else:
                # A pipeline tool must be shipped in tools/ or explicitly declared
                # by a legacy KI protocol. A preflight script is host-managed.
                from .tools import is_ki_tool
                tools_dir = Path(root) / "tools"
                ok = is_ki_tool(root, tool)
                if not ok:
                    errs.append(f"step {st.get('id')!r}: tool {tool!r} is not a runnable .py/.sh/"
                                f"executable file under {tools_dir} or a declared KI stage directory")
        for inp in st.get("inputs") or []:
            if inp and inp not in item_ids:
                errs.append(f"step {st.get('id')!r} input {inp!r} is not in the data inventory")
    for ch in plan.get("scientific_choices") or []:
        if not isinstance(ch, dict):
            errs.append("scientific choice must be an object"); continue
        if not isinstance(ch.get("high_impact"), bool):
            errs.append(f"scientific choice {ch.get('id')!r} must say high_impact true/false")
        if "options" in ch and not isinstance(ch["options"], list):
            errs.append(f"scientific choice {ch.get('id')!r} options must be an array")
    for edge in plan.get("coupling", []):
        if not isinstance(edge, dict) or ("edge_id" in edge and not isinstance(edge["edge_id"], str)):
            errs.append("coupling entries must be objects with a string edge_id when provided")
    return errs


def read_artifacts(project: Path) -> tuple[dict | None, dict | None]:
    r = Path(project) / "runs"
    out = []
    for name in ("plan.json", "data-inventory.json"):
        try:
            out.append(json.loads((r / name).read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            out.append(None)
    return out[0], out[1]


def write_artifacts(project: Path, plan: dict, inventory: dict) -> tuple[Path, Path]:
    r = Path(project) / "runs"
    r.mkdir(parents=True, exist_ok=True)
    p1, p2 = r / "plan.json", r / "data-inventory.json"
    p1.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    p2.write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    return p1, p2
