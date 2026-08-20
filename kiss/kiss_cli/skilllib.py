"""One skill library shared by GeoForge's CLI and direct-API agents."""

from __future__ import annotations

import re
from pathlib import Path


def roots() -> list[Path]:
    home = Path.home()
    return [
        home / ".agents" / "skills",
        home / ".codex" / "skills",
        home / ".claude" / "skills",
    ]


def _description(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:8000]
    except OSError:
        return ""
    match = re.search(r"^description:\s*(.*)$", text, re.MULTILINE)
    if not match:
        # A readable first heading is more useful than a blank picker row.
        heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        return heading.group(1).strip()[:240] if heading else ""
    value = match.group(1).strip().strip("'\"")
    if value not in ("|", ">", "|-", ">-"):
        return value[:240]
    lines = []
    for line in text[match.end():].splitlines():
        if line and not line[0].isspace():
            break
        if line.strip():
            lines.append(line.strip())
    return " ".join(lines)[:240]


def discover() -> list[dict]:
    """Return de-duplicated, user-callable skills from all agent homes."""
    found: dict[str, dict] = {}
    for root in roots():
        if not root.is_dir():
            continue
        for directory in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            skill = directory / "SKILL.md"
            if not directory.is_dir() or not skill.is_file():
                continue
            key = directory.name.lower()
            found.setdefault(key, {
                "name": directory.name,
                "description": _description(skill),
                "path": str(skill.resolve()),
                "source": root.parent.name.lstrip("."),
            })
    return sorted(found.values(), key=lambda item: item["name"].lower())


def by_name(name: str) -> dict | None:
    wanted = str(name or "").lower()
    return next((item for item in discover()
                 if item["name"].lower() == wanted), None)


def selected(names: list[str] | None) -> list[dict]:
    wanted = {str(name).lower() for name in (names or [])}
    return [item for item in discover() if item["name"].lower() in wanted]


def read(name: str) -> str:
    item = by_name(name)
    if not item:
        raise FileNotFoundError(f"no installed skill named {name!r}")
    return Path(item["path"]).read_text(encoding="utf-8", errors="replace")


def prompt_block(names: list[str] | None) -> str:
    chosen = selected(names)
    if not chosen:
        return ""
    lines = [
        "[SKILLS SELECTED BY THE USER FOR THIS CHAT]",
        "Read each selected SKILL.md before using it. Follow its procedure; the",
        "selection is a capability request, not permission to ignore KI rules.",
    ]
    for item in chosen:
        lines.append(f"- {item['name']}: {item['path']}")
    return "\n".join(lines)
