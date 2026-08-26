"""Give every SKILL.md the frontmatter a skill registry needs to find it.

A skill registry identifies a skill by a YAML block at the top of its
``SKILL.md``. DeepSeek Harness's filesystem provider is explicit about it:
no frontmatter, or frontmatter without both ``name`` and ``description``, and
the file is logged and skipped. Measured on this repository, only 2 of 127
packages qualify — so 125 model KIs are invisible to it, to Claude Code's skill
system, and to Pi.

The description is built from the KI's own ``dag.yaml`` rather than written by
hand. That keeps 127 descriptions consistent, makes them regenerable when a dag
changes, and means the text says what the model actually claims about itself
instead of what someone guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

#: Registries require kebab-case. DeepSeek Harness rejects anything else.
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: Keep descriptions in the range a catalogue can display without truncating.
MAX_DESCRIPTION = 480


def slug(model: str) -> str:
    """Kebab-case registry name for a model directory."""
    s = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    if not NAME_RE.match(s):
        raise ValueError(f"cannot derive a legal skill name from {model!r} (got {s!r})")
    return s


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "…"


def describe(ki) -> str:
    """One line: what this model is, and when an agent should reach for it.

    Assembled from dag.yaml — the reference version names the model, the
    boundary's scope says what it is *for*. Falls back to the model name alone
    rather than inventing capability that cannot be verified.

    The budget is allocated deliberately rather than by truncating the finished
    string. A registry matches a query against this text, so the "Use when..."
    clause is the most load-bearing part and must never be the bit that gets
    cut; scope detail is what gives way instead.
    """
    meta = ki.meta or {}
    ref = meta.get("reference") or ""
    # Drop a trailing parenthetical citation: it identifies the paper, not the
    # capability, and would eat budget the scope needs.
    ref = re.sub(r"\s*\([^)]*\b(?:et al|GMD|JGR|TM |19\d\d|20\d\d)\b[^)]*\)\s*$",
                 "", ref).strip(" ;,")

    use = (f"Use when the task involves running, configuring, calibrating or "
           f"interpreting {ki.name}.")

    head = _clip(ref or ki.name, 150)
    if not head.endswith("."):
        head += "."

    remaining = MAX_DESCRIPTION - len(head) - len(use) - 2
    scope_text = ""
    if remaining > 40 and ki.dag and yaml is not None:
        try:
            doc = yaml.safe_load(ki.dag.read_text(encoding="utf-8", errors="replace")) or {}
            scope = [str(s) for s in (doc.get("boundary") or {}).get("scope_in", [])]
        except Exception:
            scope = []
        picked: list[str] = []
        budget = remaining - len("Covers .")
        for s in scope:
            s = _clip(s, 100).rstrip(".")
            if len(s) + 2 > budget:
                break
            picked.append(s)
            budget -= len(s) + 2
        if picked:
            scope_text = "Covers " + "; ".join(picked) + "."

    return " ".join(x for x in (head, scope_text, use) if x)


def existing_block(text: str) -> tuple[dict, str] | None:
    """Parse leading frontmatter, returning (data, body) or None."""
    if not text.startswith("---"):
        return None
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return None
    if yaml is None:
        return None
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data, text[m.end():]


def render(data: dict) -> str:
    """Emit a frontmatter block with the keys in a stable order.

    Values are serialised by PyYAML rather than interpolated. Hand-writing
    ``key: value`` is wrong for a surprising number of ordinary descriptions:
    ``Use when a: b`` is invalid YAML, a leading ``-`` reads as a sequence,
    an unquoted ``#`` truncates the value at the comment, and a bare ``yes``
    loads as the boolean True. The generated text happens to avoid all of these
    today, which is exactly the kind of thing that breaks silently later.
    """
    if yaml is None:
        raise RuntimeError("pyyaml is required to render frontmatter")

    order = ["name", "description", "allowed-tools", "version", "model", "domain"]
    keys = [k for k in order if k in data] + [k for k in data if k not in order]

    lines = ["---"]
    for k in keys:
        chunk = yaml.safe_dump({k: data[k]}, default_flow_style=False,
                               allow_unicode=True, width=88, sort_keys=False)
        lines.append(chunk.rstrip("\n"))
    lines.append("---")
    return "\n".join(lines) + "\n"


@dataclass
class FmResult:
    model: str
    action: str            # "added" | "completed" | "kept" | "failed"
    name: str = ""
    detail: str = ""


@dataclass
class FmReport:
    results: list[FmResult] = field(default_factory=list)

    def by_action(self, a: str) -> list[FmResult]:
        return [r for r in self.results if r.action == a]


def apply_to(ki, *, dry_run: bool = False) -> FmResult:
    """Ensure ``ki``'s SKILL.md carries a registry-valid frontmatter block.

    Existing frontmatter is preserved and only completed — several packages
    already carry ``version``/``model``/``domain`` keys that are worth keeping,
    and two carry a hand-written description better than anything generated.
    """
    if ki.skill is None:
        return FmResult(ki.name, "failed", detail="no SKILL.md")

    text = ki.skill.read_text(encoding="utf-8")
    found = existing_block(text)
    want_name = slug(ki.name)

    if found is None:
        data, body = {}, text
        action = "added"
    else:
        data, body = found
        action = "kept" if (NAME_RE.match(str(data.get("name", "")))
                            and data.get("description")) else "completed"

    if not NAME_RE.match(str(data.get("name", ""))):
        data["name"] = want_name
    if not data.get("description"):
        data["description"] = describe(ki)

    if action == "kept":
        return FmResult(ki.name, "kept", data["name"], "already valid")

    new_text = render(data) + "\n" + body.lstrip("\n")
    if not dry_run:
        ki.skill.write_text(new_text, encoding="utf-8")
    return FmResult(ki.name, action, data["name"],
                    _clip(data["description"], 70))


def apply_all(catalog, *, dry_run: bool = False) -> FmReport:
    rep = FmReport()
    for ki in catalog:
        try:
            rep.results.append(apply_to(ki, dry_run=dry_run))
        except Exception as e:  # never abort the batch on one package
            rep.results.append(FmResult(ki.name, "failed", detail=str(e)[:80]))
    return rep
