"""Pure, provider-neutral targets for explicitly planned public-file downloads.

One inventory item is one file. This module neither downloads nor grants readiness.
Database deliveries and executable data-KI steps retain their existing contracts.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse

DATABASE_DELIVERIES = frozenset({"served", "subset", "manual"})


def _component(value, limit, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f"public download {label} must be a nonempty string")
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in value)[:limit]
    stem = safe.split(".", 1)[0].upper()
    if (safe in {"", ".", ".."} or safe.endswith((".", " "))
            or stem in {"CON", "PRN", "AUX", "NUL"}
            or stem in {f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)}):
        raise ValueError(f"public download {label} is not a portable file component")
    return safe


def target(item_id, url, filename=None):
    """Return the exact future relative file path without I/O or redirects."""
    if not isinstance(url, str) or len(url) > 8192:
        raise ValueError("public download chosen_source must be one exact http(s) URL")
    try:
        parsed = urlparse(url)
        valid = (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                 and not parsed.username and not parsed.password
                 and not any(ord(c) < 32 for c in url))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("public download chosen_source must be one exact public http(s) URL without userinfo")
    component = _component(item_id, 80, "item_id")
    name = _component(filename if filename is not None else
                      (PurePosixPath(parsed.path).name or "download.bin"), 160, "filename")
    path = f"inputs/raw/{component}/{name}"
    return {"item_id": item_id, "url": url, "filename": name, "path": path,
            "inventory": {"chosen_source": url, "local_paths": [path]},
            "grants_readiness": False}


def _public_file_hint(item):
    # Legacy catalogue identifiers without a public-file declaration are not URLs.
    sources = [item.get("chosen_source")] + (item.get("acceptable_sources") or []
              if isinstance(item.get("acceptable_sources"), list) else [])
    paths = item.get("local_paths") if isinstance(item.get("local_paths"), list) else []
    return (any(isinstance(s, str) and s.lower().startswith(("http://", "https://")) for s in sources)
            or any(isinstance(p, str) and p.startswith("inputs/raw/") for p in paths))


def public_items(step, inventory):
    """Only explicit non-KI download outputs; never reinterpret DB selections."""
    if step.get("kind") != "download" or step.get("tool"):
        return []
    by_id = {i["id"]: i for i in inventory.get("items", [])
             if isinstance(i, dict) and isinstance(i.get("id"), str)}
    outputs = step.get("outputs")
    outputs = outputs if isinstance(outputs, list) else []
    return [by_id[i] for i in outputs if isinstance(i, str) and i in by_id
            and by_id[i].get("delivery") not in DATABASE_DELIVERIES
            and not by_id[i].get("dataset_id") and _public_file_hint(by_id[i])]


def binding(item):
    """Validate existing fields; a basename is an explicit reviewed filename."""
    ident = item.get("id")
    paths = item.get("local_paths")
    folder = f"inputs/raw/{_component(ident, 80, 'item_id')}/"
    if not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], str):
        raise ValueError(f"public download item {ident!r}: one file per item is required; "
                         f"declare exactly one local_paths entry under {folder}. "
                         "acceptable_sources are alternatives, not a multi-file download list")
    raw = paths[0]
    if "\\" in raw or raw.endswith("/"):
        raise ValueError(f"public download item {ident!r}: use one exact file under {folder}")
    result = target(ident, item.get("chosen_source"), PurePosixPath(raw).name)
    if raw != result["path"]:
        raise ValueError(f"public download item {ident!r}: local_paths {raw!r} does not match "
                         f"the host download target {result['path']!r}; query describe_download_target")
    return result


def plan_errors(plan, inventory):
    errors, targets = [], {}
    for step in plan.get("steps", []):
        if not isinstance(step, dict) or step.get("status") == "skipped":
            continue
        for item in public_items(step, inventory):
            try:
                row = binding(item)
                folded = str(PurePosixPath(row["path"]).parent).casefold()
                if folded in targets and targets[folded] != item["id"]:
                    raise ValueError(f"public download items {targets[folded]!r} and "
                                     f"{item['id']!r} resolve to the same portable target directory/receipt key")
                targets[folded] = item["id"]
            except ValueError as error:
                errors.append(f"step {step.get('id')!r}: {error}")
    return errors


def step_complete(step, inventory, receipts):
    """All declared files need exact current receipts; no scientific claim."""
    strict = {item["id"]: item for item in public_items(step, inventory)}
    if not strict:
        return True  # Caller retains the legacy receipt eligibility conditions.
    outputs = step.get("outputs") or []
    for ident in outputs:
        matches = [r for r in receipts if r.get("item_id") == ident
                   and r.get("plan_step_id") == step.get("id")]
        if ident in strict:
            try:
                expected = binding(strict[ident])
            except ValueError:
                return False
            matches = [r for r in matches if r.get("request_url") == expected["url"]
                       and [f.get("path") for f in r.get("raw_files", [])] == [expected["path"]]
                       and not r.get("processed_files")]
        if not matches:
            return False
    return bool(outputs)
