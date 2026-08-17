"""Rewrite authoring-machine paths into placeholders.

The shipped KIs carry one machine's absolute paths. The sandbox can *fake* those
paths, but that only works on Linux, only inside the namespace, and it leaves a
public repository full of someone's private directory layout. Placeholders fix
the packages themselves, so a KI is portable by construction rather than by
trick.

Token form is ``KISSPATH_ROLE``. It was chosen by elimination — the obvious
candidates all break something:

* ``{{KISS_DATA}}`` — ``{`` opens a flow mapping in YAML. Measured: it broke 43
  of the 127 packages' ``format_spec.yaml`` / ``validation_convention.yaml``.
* ``<KISS_DATA>`` — YAML-safe, but GitHub renders it as an HTML tag and the
  placeholder *disappears* from the rendered SKILL.md.
* ``__KISS_DATA__`` — YAML-safe, but Markdown renders it bold, losing the
  underscores a user would need to type.
* ``$KISS_DATA`` / ``${KISS_DATA}`` — a shell expands them to nothing and then
  reads ``/forcing.nc`` from the filesystem root. Fails silently, which is the
  one behaviour to avoid.

``KISSPATH_DATA`` is plain text: safe in YAML, JSON, shell and Markdown, easy to
grep, and an unsubstituted token fails loudly as
``KISSPATH_DATA/forcing.nc: No such file`` — naming the role that was not
configured.

Safety: this rewrites 600-odd files across 127 packages, so every edit is
verified before it is kept. A Python file that no longer parses, or any file
whose only change is not a path substitution, is reverted and reported. That
check exists because the last automated pass over this repository silently
corrupted two ``preflight_check.py`` files — the entry point users run first.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from .paths import LEAK_ROLES, LEGACY_PREFIXES

#: Placeholder for each role. ``kdt_internal`` is tokenised rather than deleted:
#: removing text mid-sentence corrupts meaning, and a visible token lets
#: ``kiss doctor`` keep flagging it until someone cleans it up properly.
TOKENS: dict[str, str] = {
    "python_env": "KISSPATH_PYTHON_ENV",
    "ki_tools_common": "KISSPATH_KI_TOOLS_COMMON",
    "ki_root": "KISSPATH_KI_ROOT",
    "binaries": "KISSPATH_BINARIES",
    "obs": "KISSPATH_OBS",
    "static": "KISSPATH_STATIC",
    "data": "KISSPATH_DATA",
    "forcing": "KISSPATH_FORCING",
    "outputs": "KISSPATH_OUTPUTS",
    "outputs_disk1": "KISSPATH_OUTPUTS_ALT",
    "data_ki": "KISSPATH_DATA_KI",
    "forcing_rechunked": "KISSPATH_FORCING_RECHUNKED",
    "server_root": "KISSPATH_ROOT",
    "home": "KISSPATH_HOME",
    "kdt_internal": "KISSPATH_INTERNAL_NOT_SHIPPED",
}

TOKEN_RE = re.compile(r"KISSPATH_[A-Z_]+")

TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".sh", ".txt", ".cfg", ".ini",
                 ".json", ".toml", ".nml", ".inp"}

#: Longest prefix first, so ``.../data/obs`` is replaced before ``.../data``.
_ORDERED = sorted(LEGACY_PREFIXES, key=lambda pr: len(pr[0]), reverse=True)

#: Elided paths written by hand in prose and comments — "/mnt/disk1/.../soil/x".
#: A literal prefix match never sees these because the middle is an ellipsis, so
#: they survived the first pass and still leaked the disk layout.
ELIDED = [
    (r"/mnt/disk1/\.\.\.", "KISSPATH_ROOT/..."),
    (r"/mnt/disk1(?![\w/])", "KISSPATH_ROOT"),
    (r"/mnt/disk3(?![\w/])", "KISSPATH_DATA"),
    (r"/mnt/disk1/project", "KISSPATH_ROOT"),
    (r"/media/server(?![\w])", "KISSPATH_DATA"),
    (r"/home/server(?![\w])", "KISSPATH_HOME"),
]


@dataclass
class FileResult:
    path: Path
    replaced: int = 0
    reverted: bool = False
    why: str = ""


@dataclass
class PortReport:
    files: list[FileResult] = field(default_factory=list)
    skipped_binary: int = 0

    @property
    def changed(self) -> list[FileResult]:
        return [f for f in self.files if f.replaced and not f.reverted]

    @property
    def reverted(self) -> list[FileResult]:
        return [f for f in self.files if f.reverted]

    @property
    def total_replacements(self) -> int:
        return sum(f.replaced for f in self.changed)


def substitute(text: str) -> tuple[str, int]:
    """Replace every authoring prefix with its role token."""
    n = 0
    for prefix, role in _ORDERED:
        token = TOKENS.get(role)
        if not token:
            continue
        if prefix in text:
            n += text.count(prefix)
            text = text.replace(prefix, token)
    for pat, repl in ELIDED:
        text, k = re.subn(pat, repl, text)
        n += k
    return text, n


def _still_valid(path: Path, new_text: str) -> tuple[bool, str]:
    """Would this rewrite leave the file usable?"""
    if path.suffix == ".py":
        try:
            ast.parse(new_text)
        except SyntaxError as e:
            return False, f"python no longer parses at line {e.lineno}"
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
            yaml.safe_load(new_text)
        except Exception as e:
            return False, f"yaml no longer parses: {str(e)[:60]}"
    if path.suffix == ".json":
        import json
        try:
            json.loads(new_text)
        except Exception as e:
            return False, f"json no longer parses: {str(e)[:60]}"
    return True, ""


def port_file(path: Path, *, dry_run: bool = False) -> FileResult:
    res = FileResult(path=path)
    try:
        original = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return res  # binary or unreadable — never touched

    new_text, n = substitute(original)
    if n == 0:
        return res
    res.replaced = n

    # A rewrite must change nothing except the paths. If the file was already
    # broken before we touched it, note that and leave it alone rather than
    # taking the blame for it.
    was_ok, _ = _still_valid(path, original)
    ok, why = _still_valid(path, new_text)
    if not ok:
        res.reverted = True
        res.why = why if was_ok else f"{why} (already broken before porting)"
        return res

    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return res


def port_tree(root: Path, *, dry_run: bool = False) -> PortReport:
    rep = PortReport()
    for f in sorted(Path(root).rglob("*")):
        if not f.is_file():
            continue
        if f.suffix.lower() not in TEXT_SUFFIXES:
            rep.skipped_binary += 1
            continue
        r = port_file(f, dry_run=dry_run)
        if r.replaced:
            rep.files.append(r)
    return rep


def render_config_template(roles: list[str] | None = None) -> str:
    """The template a user fills in, listing every role a ported KI needs."""
    roles = roles or [r for r in TOKENS if r not in LEAK_ROLES]
    lines = [
        "# KISS paths — fill these in for this machine.",
        "# Each entry replaces the matching KISSPATH_* placeholder in the KI.",
        "",
        "[paths]",
    ]
    for role in roles:
        lines.append(f'# {TOKENS[role]}')
        lines.append(f'{role} = ""')
    return "\n".join(lines) + "\n"
