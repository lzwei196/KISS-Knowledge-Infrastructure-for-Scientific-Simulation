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
import os
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
PYTHON_TOKEN = "KISSPATH_PYTHON"
# The active package is not the catalogue root and cannot be configured as a
# user role. Only the host projecting a KI knows its final logical directory.
CURRENT_KI_TOKEN = "KISSPATH_CURRENT_KI"

# Older generated KIs can still contain paths into the private KDT build
# scratch tree.  The private prefix is unavailable on every desktop, but the
# model-relative suffix is portable and belongs below the configured binaries
# root.  Keep this deliberately limited to known _work layouts; unrelated
# private caches must remain unresolved instead of being guessed.
_INTERNAL_WORK_PATH = re.compile(
    r"KISSPATH_INTERNAL_NOT_SHIPPED/"
    r"auto_dissect(?:_multi_agent)?/_work(?:_v2)?/"
    r"(?P<model>[^/\s\"'<>`]+)"
    r"(?:/(?P<rest>[^\s\"'<>`\]\[),;]*))?"
)
_INTERNAL_SPLIT_LITERAL = re.compile(
    r'(?P<q>["\'])(?P<a>[^"\']*KISSPATH_INTERNAL_NOT_SHIPPED[^"\']*)'
    r'(?P=q)\s*(?P=q)(?P<b>[^"\']*)(?P=q)',
    re.S,
)
_INTERNAL_VENV_PYTHON = re.compile(
    r"KISSPATH_INTERNAL_NOT_SHIPPED/"
    r"auto_dissect(?:_multi_agent)?/_work(?:_v2)?/"
    r"[^/\s\"'<>`]+/venv/bin/python(?:\d+(?:\.\d+)*)?"
)
_INTERNAL_VENV_SITE = re.compile(
    r"KISSPATH_INTERNAL_NOT_SHIPPED/"
    r"auto_dissect(?:_multi_agent)?/_work(?:_v2)?/"
    r"[^/\s\"'<>`]+/venv/lib/python[^/\s\"'<>`]+/site-packages"
)
_INTERNAL_SHARED_ROOT = re.compile(
    r"KISSPATH_INTERNAL_NOT_SHIPPED/"
    r"auto_dissect(?:_multi_agent)?"
    r"(?:/ki_tools_common)?"
)

# KIs authored on the HydroCraft server build paths from the server root in
# code: ``ROOT / "model" / "hype"``, ``os.path.join(HYDROCRAFT_ROOT, "python_env",
# "bin", "python")``, ``f"{BASE}/data/obs/..."``. Publishing replaced the root
# literal with KISSPATH_ROOT but kept the relative parts, so binding wrote
# ``<project>/model/...`` -- a place a desktop never has. LEGACY_PREFIXES already
# describes the server layout (model -> binaries, python_env -> python_env,
# data/obs -> obs, ...); the same rows are applied to those root-relative parts,
# so each path lands in the role its absolute spelling would have.
#
# Only port.materialise opts in, per KI. SHAW and WOFOST are excluded: their
# maintenance recipes (ki_maintenance_shaw, ki_path_contracts/ki_fresh_paths)
# recognise the published files and their plain role expansion exactly.
SERVER_LAYOUT_EXCLUDED_KIS = frozenset({"SHAW", "WOFOST"})


def _server_rows() -> list[tuple[str, str]]:
    root = next(prefix for prefix, role in LEGACY_PREFIXES if role == "server_root")
    rows = [(prefix[len(root) + 1:], role) for prefix, role in LEGACY_PREFIXES
            if prefix.startswith(root + "/")]
    return sorted(rows, key=lambda row: len(row[0]), reverse=True)


_SERVER_ROWS = _server_rows()
_SERVER_TEXT = re.compile(r"KISSPATH_ROOT/(?P<rel>[^\s'\"`<>)\]},;{]+)")
_PATH_CALLS = {"Path", "PurePath", "PurePosixPath", "PureWindowsPath"}


def server_layout_applies(name: str | None) -> bool:
    return name not in SERVER_LAYOUT_EXCLUDED_KIS


def package_name(ki_root: Path) -> str:
    """The KI's declared ``package.name``; its folder name when undeclared.

    Drafts live in ``candidate/`` and project copies in ``ki/``, so the folder
    alone cannot identify the package.
    """
    import yaml
    try:
        doc = yaml.safe_load((Path(ki_root) / "knowledge_infrastructure.yaml").read_text(encoding="utf-8"))
        name = doc["package"]["name"]
        if isinstance(name, str) and name:
            return name
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        pass
    return Path(ki_root).name


def _server_relative(rel: str) -> str | None:
    """``data/obs/x`` -> ``KISSPATH_OBS/x``; None when no LEGACY_PREFIXES row applies."""
    clean = rel.strip("/")
    for prefix, role in _SERVER_ROWS:
        if clean == prefix or clean.startswith(prefix + "/"):
            rest = clean[len(prefix):].lstrip("/")
            mapped = f"{TOKENS[role]}/{rest}" if rest else TOKENS[role]
            return mapped + "/" if rel.endswith("/") else mapped
    return None


def _server_root_names(tree: ast.AST) -> set[str]:
    """Names whose every assignment is the server root."""
    values: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    values.setdefault(target.id, []).append(node.value)
    roots: set[str] = set()
    while True:
        found = {name for name, assigned in values.items()
                 if name not in roots and all(_is_server_root(v, roots) for v in assigned)}
        if not found:
            return roots
        roots |= found


def _is_server_root(node: ast.AST, roots: set[str]) -> bool:
    if isinstance(node, ast.Constant):
        return node.value == "KISSPATH_ROOT"
    if isinstance(node, ast.Name):
        return node.id in roots
    if isinstance(node, ast.Call):
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name in _PATH_CALLS | {"str", "fspath", "abspath", "realpath", "expanduser"} and len(node.args) == 1:
            return _is_server_root(node.args[0], roots)
        if name in {"get", "getenv"} and len(node.args) == 2:   # os.environ.get("HYDROCRAFT_ROOT", root)
            return _is_server_root(node.args[1], roots)
        if isinstance(func, ast.Attribute) and name in {"resolve", "absolute", "expanduser"} and not node.args:
            return _is_server_root(func.value, roots)
    return False


def _strings(nodes) -> list[str]:
    """The leading run of string literals."""
    run = []
    for node in nodes:
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            break
        run.append(node.value)
    return run


def _joined(run: list[str]) -> str:
    return "/".join(part.strip("/") for part in run if part.strip("/"))


def _rewrite_server_python(text: str) -> tuple[str, int]:
    """Rewrite root-built Python path expressions; unchanged unless the result parses."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return text, 0
    roots = _server_root_names(tree)
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))

    def offset(lineno: int, col: int) -> int:
        line = lines[lineno - 1]
        return starts[lineno - 1] + len(line.encode("utf-8")[:col].decode("utf-8", "ignore"))

    # Bracket tokens by absolute offset. Python positions a parenthesised operand
    # without its parentheses -- ROOT / ("a/" "b") -- so a span ending at that
    # operand must also take the ")" that closes inside the replaced text.
    import io
    import tokenize
    opens, closes = [], []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.OP and tok.string in "()":
                at = starts[tok.start[0] - 1] + tok.start[1]
                (opens if tok.string == "(" else closes).append(at)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return text, 0

    def span(first: ast.AST, last: ast.AST) -> tuple[int, int]:
        begin = offset(first.lineno, first.col_offset)
        end = offset(last.end_lineno, last.end_col_offset)
        unclosed = sum(begin <= at < end for at in opens) - sum(begin <= at < end for at in closes)
        for at in closes:
            if unclosed <= 0:
                break
            if at >= end:
                end, unclosed = at + 1, unclosed - 1
        return begin, end

    path_bound = any(isinstance(n, ast.ImportFrom) and any((a.asname or a.name) == "Path" for a in n.names)
                     for n in ast.walk(tree))

    def quote(node: ast.AST) -> str:
        # Reuse the replaced literal's quote: it may sit inside an f-string
        # of the other quote, which Python < 3.12 cannot nest.
        source = text[offset(node.lineno, node.col_offset):].lstrip("( \t\r\n").lstrip("rRbBuU")
        return source[0] if source[:1] in {"'", '"'} else '"'

    def path_of(mapped: str, q: str) -> str:
        call = "Path" if path_bound else f"__import__({q}pathlib{q}).Path"
        return f"{call}({q}{mapped}{q})"

    edits: dict[tuple[int, int], str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
            chain, left = [], node
            while isinstance(left, ast.BinOp) and type(left.op) is type(node.op):
                chain.insert(0, left)
                left = left.left
            run = _strings(link.right for link in chain)
            if not run or not _is_server_root(left, roots):
                continue
            q = quote(chain[0].right)
            if isinstance(node.op, ast.Div):
                mapped = _server_relative(_joined(run))
                replacement = mapped and path_of(mapped, q)
            else:
                joined = "".join(run)
                mapped = joined.startswith("/") and _server_relative(joined)
                replacement = mapped and f"{q}{mapped}{q}"
            if replacement:
                edits[span(left, chain[len(run) - 1].right)] = replacement
        elif isinstance(node, ast.Call) and node.args and not node.keywords:
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            joins = (name == "join" and isinstance(func, ast.Attribute)
                     and not isinstance(func.value, ast.Constant)) or name in _PATH_CALLS
            if joins and len(node.args) >= 2 and _is_server_root(node.args[0], roots):
                run = _strings(node.args[1:])
                mapped = run and _server_relative(_joined(run))
                if mapped:
                    q = quote(node.args[1])
                    edits[span(node.args[0], node.args[len(run)])] = f"{q}{mapped}{q}"
            elif (name == "joinpath" and isinstance(func, ast.Attribute)
                  and _is_server_root(func.value, roots)):
                run = _strings(node.args)
                mapped = run and len(run) == len(node.args) and _server_relative(_joined(run))
                if mapped:
                    edits[span(node, node)] = path_of(mapped, quote(node.args[0]))
        elif isinstance(node, ast.JoinedStr) and roots:
            begin, end = span(node, node)
            source = text[begin:end]

            def fstring(match: "re.Match") -> str:
                mapped = _server_relative(match.group("rel"))
                return mapped if mapped else match.group(0)

            names = "|".join(re.escape(name) for name in sorted(roots))
            rewritten = re.sub(r"\{\s*(?:" + names + r")\s*\}(?P<rel>/[^{}'\"\\]+)", fstring, source)
            if rewritten != source:
                edits[(begin, end)] = rewritten

    applied, cursor, out = 0, len(text), []
    for begin, end in sorted(edits, reverse=True):
        if end > cursor:            # overlaps an edit already taken: leave it as written
            continue
        out.append(text[end:cursor])
        out.append(edits[(begin, end)])
        cursor = begin
        applied += 1
    out.append(text[:cursor])
    result = "".join(reversed(out))
    try:
        ast.parse(result)
    except (SyntaxError, ValueError):
        return text, 0
    return result, applied


def _migrate_server_layout(text: str) -> tuple[str, int]:
    """Map server-root-relative paths through LEGACY_PREFIXES (code first, then text)."""
    if "KISSPATH_ROOT" not in text:
        return text, 0
    text, changed = _rewrite_server_python(text)

    def plain(match: "re.Match") -> str:
        nonlocal changed
        mapped = _server_relative(match.group("rel"))
        if not mapped:
            return match.group(0)
        changed += 1
        return mapped

    return _SERVER_TEXT.sub(plain, text), changed


TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".sh", ".txt", ".cfg", ".ini",
                 ".json", ".toml", ".nml", ".inp"}

#: Longest prefix first, so ``.../data/obs`` is replaced before ``.../data``.
_ORDERED = sorted(LEGACY_PREFIXES, key=lambda pr: len(pr[0]), reverse=True)

#: Elided paths written by hand in prose and comments — "/mnt/disk1/.../soil/x".
#: A literal prefix match never sees these because the middle is an ellipsis, so
#: they survived the first pass and still leaked the disk layout.
#: Each pattern carries its own boundary; the main prefix pass is bounded but
#: these were not, so an elided path inside a longer word was still rewritten.
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


#: A prefix only matches when what follows it is a path boundary. Without this,
#: "/mnt/disk3_backup/x" became "KISSPATH_DATA_backup/x" — a prefix eating part
#: of a longer directory name. Measured: this is how "/mnt/disk3/msxw_rechunked"
#: first turned into "KISSPATH_FORCING_rechunked".
_BOUNDARY = r"(?![\w-])"

_SUB_RE = re.compile(
    "|".join(f"(?P<r{i}>{re.escape(pref)}{_BOUNDARY})"
             for i, (pref, _) in enumerate(_ORDERED))
)
_SUB_ROLE = {f"r{i}": role for i, (_, role) in enumerate(_ORDERED)}


def substitute(text: str) -> tuple[str, int]:
    """Replace every authoring prefix with its role token.

    One regex pass, longest prefix first. A sequence of str.replace calls would
    rescan text it had already written, so a token could be matched again by a
    later, shorter prefix.
    """
    n = 0

    def repl(m: "re.Match") -> str:
        nonlocal n
        role = _SUB_ROLE[m.lastgroup]
        token = TOKENS.get(role)
        if not token:
            return m.group(0)
        n += 1
        return token

    text = _SUB_RE.sub(repl, text)
    for pat, replacement in ELIDED:
        text, k = re.subn(pat, replacement, text)
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


# --- the other direction: placeholders -> this machine ----------------------

def _portable(target) -> str:
    """The real path, written so it survives being pasted into source.

    Tokens sit inside string literals -- ``_penv = "KISSPATH_PYTHON_ENV/lib"``
    is the shape every KI uses -- so a native Windows path puts a lone
    backslash in there and \\U opens an escape that is not valid in Python,
    JSON or TOML. Every KI carrying such a line was rejected as "corrupted
    paths" and setup could not start; on macOS the same path has no backslash
    and the problem never appears.

    Forward slashes avoid the escape entirely and Windows accepts them in
    every file API, so the materialised copy is both parseable and runnable.
    """
    text = str(target)
    return text.replace('\\', "/") if os.name == "nt" else text


def _current_ki_target(ki_target) -> Path | None:
    """Validate a host-supplied logical target without resolving a staging tree."""
    if ki_target is None:
        return None
    try:
        target = Path(ki_target)
    except (TypeError, ValueError) as error:
        raise ValueError("Current KI target must be an absolute path") from error
    if (not target.is_absolute() or TOKEN_RE.search(str(target))
            or "\x00" in str(target)):
        raise ValueError("Current KI target must be absolute and contain no path tokens")
    return target


def unsubstitute(text: str, cfg, *, ki_target=None,
                 server_layout: bool = False) -> tuple[str, int, set[str]]:
    """Replace ``KISSPATH_*`` tokens with real paths from ``cfg``.

    ``server_layout`` also maps paths built from the server root through
    LEGACY_PREFIXES (see ``_migrate_server_layout``). Only ``materialise`` sets
    it, per KI; other callers expand literals exactly as before.

    ``KISSPATH_CURRENT_KI`` is bound only by the optional host-supplied
    ``ki_target``: the final package directory, which may differ from the
    physical directory where a projection is being prepared. It is never
    taken from ``cfg.roles`` or inferred from the source/destination.

    Single regex pass, longest token first. Replacing sequentially would rescan
    text already written, so a real directory whose name happens to contain a
    token — ``/tmp/KISSPATH_DATA/ki`` is a legal path — would be corrupted by a
    later substitution.

    Returns the new text, how many tokens were replaced, and the set of tokens
    with no configured role. Those are left in place on purpose: they then fail
    at the point of use naming the role, rather than collapsing to a plausible
    wrong path. Tokens for LEAK_ROLES are skipped entirely — they mark
    references to tooling that cannot exist here, and are reported by the caller
    rather than counted as failures.
    """
    current_ki_target = _current_ki_target(ki_target)
    # Adjacent Python literals form one path at runtime. Join only literals
    # carrying the private marker so the migration rules see the full suffix.
    joined = 0
    for _ in range(8):
        text, changed = _INTERNAL_SPLIT_LITERAL.subn(
            lambda match: (
                f"{match.group('q')}{match.group('a')}"
                f"{match.group('b')}{match.group('q')}"
            ),
            text,
        )
        joined += changed
        if not changed:
            break

    # A private model venv maps to the configured desktop Python environment,
    # not to the model's binary checkout. Recognise it before the broader
    # per-model _work migration.
    text, migrated_python = _INTERNAL_VENV_PYTHON.subn(
        "KISSPATH_PYTHON_ENV/bin/python", text)
    text, migrated_sites = _INTERNAL_VENV_SITE.subn(
        "KISSPATH_PYTHON_ENV", text)

    def migrate_work_path(match: "re.Match") -> str:
        suffix = "/".join(filter(None, (
            match.group("model"), match.group("rest") or "")))
        return f"KISSPATH_BINARIES/{suffix}"

    text, migrated_work = _INTERNAL_WORK_PATH.subn(migrate_work_path, text)
    text, migrated_shared = _INTERNAL_SHARED_ROOT.subn(
        "KISSPATH_KI_TOOLS_COMMON", text)
    text, migrated_server = _migrate_server_layout(text) if server_layout else (text, 0)

    # Older KIs describe the interpreter as
    # ``KISSPATH_PYTHON_ENV/bin/python``.  Substituting only the environment
    # directory produces a path that can never exist in a Windows venv, whose
    # interpreter lives below Scripts/python.exe.  Normalize that legacy
    # compound placeholder to an executable token before the ordinary role
    # expansion.  New KIs can use KISSPATH_PYTHON directly.
    text, python_compat = re.subn(
        r"KISSPATH_PYTHON_ENV[/\\]bin[/\\]python(?:3)?(?![\w.])",
        PYTHON_TOKEN,
        text,
    )
    by_token = {tok: role for role, tok in TOKENS.items()}
    by_token[PYTHON_TOKEN] = "__python_executable__"
    by_token[CURRENT_KI_TOKEN] = "__current_ki__"
    undeliverable = {tok for tok, role in by_token.items() if role in LEAK_ROLES}
    unresolved: set[str] = set()
    n = (joined + migrated_python + migrated_sites + migrated_work +
         migrated_shared + migrated_server)

    ordered = sorted(by_token, key=len, reverse=True)
    pattern = re.compile("|".join(
        (r"(?<!\w)" + re.escape(tok) + r"(?!\w)")
        if tok == CURRENT_KI_TOKEN else re.escape(tok)
        for tok in ordered
    ))

    def repl(m: "re.Match") -> str:
        nonlocal n
        tok = m.group(0)
        if tok in undeliverable:
            return tok
        role = by_token[tok]
        if role == "__current_ki__":
            target = current_ki_target
        else:
            target = getattr(cfg, "python", None) if role == "__python_executable__" else cfg.roles.get(role)
        if target is None:
            unresolved.add(tok)
            return tok
        # A role whose configured path itself contains a placeholder would emit
        # the token straight back out, and the single-pass design means nothing
        # would catch it on a rescan. Reject it as unresolved rather than
        # reporting a substitution that changed nothing.
        if TOKEN_RE.search(str(target)):
            unresolved.add(tok)
            return tok
        n += 1
        return _portable(target)

    text = pattern.sub(repl, text)
    return text, n + python_compat, unresolved


@dataclass
class MaterialiseReport:
    dest: Path
    files_written: int = 0
    tokens_replaced: int = 0
    unresolved: set[str] = field(default_factory=set)
    #: files still carrying a reference that cannot ever resolve on this machine
    undeliverable_files: int = 0
    undeliverable: list[str] = field(default_factory=list)
    #: files that stopped parsing once the real path was written in
    corrupted: list[str] = field(default_factory=list)
    skipped: int = 0


def validate_materialisation_destination(dest: Path) -> Path:
    """Reject escaping, broken or cyclic destination aliases before refresh.

    Resolve the parent (which may use an OS alias such as /tmp) but never
    follow a symlink at the destination root. Internal aliases are inventoried
    without traversal; materialise separately checks their source mapping and
    writes only canonical entries. Callers own the parent directory; Desktop validates the
    project/models/<KI> namespace. No links are removed or repaired here.
    """
    import stat
    dest = Path(dest).expanduser()
    try:
        info = dest.lstat()
    except FileNotFoundError:
        info = None
    if info is not None and (stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) &
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise ValueError(f"KI destination is a symlink or reparse point; review it before refreshing: {dest}")
    dest = dest.resolve()
    if dest.exists():
        if not dest.is_dir():
            raise ValueError(f"KI destination is not a directory: {dest}")
        from . import ki_tree
        try:
            ki_tree.scan(dest)
        except ValueError as error:
            raise ValueError(f"KI destination contains an unsafe symlink or entry: {error}") from error
    return dest


def materialise(ki_root: Path, dest: Path, cfg, *, ki_target=None) -> MaterialiseReport:
    """Copy a placeholder KI to ``dest`` with real paths written in.

    This is what makes a ported KI runnable. The installed copy contains
    concrete paths, so the model's own tools, configs and preflight work
    without a namespace faking anything — the sandbox becomes a safety choice
    rather than a requirement for correctness.

    The original package is never modified; ``dest`` is a working copy.
    ``ki_target`` binds the current-package token to the final logical target,
    not this potentially temporary destination. With no target it stays
    unresolved, as do other unconfigured runtime tokens.
    """
    import shutil
    from . import ki_copy, ki_tree

    ki_target = _current_ki_target(ki_target)
    ki_root = Path(ki_root)
    inventory = ki_tree.scan(ki_root)
    source_identity = ki_tree.digest(ki_root)
    if not source_identity:
        raise ValueError("Cannot establish KI source identity before materialisation")
    server_layout = server_layout_applies(package_name(ki_root))
    dest = validate_materialisation_destination(dest)
    source_root = ki_root.resolve()
    if source_root == dest or source_root in dest.parents or dest in source_root.parents:
        raise ValueError("KI source and materialisation destination must be separate trees")
    aliases = {entry.relative: entry.target for entry in inventory.entries if entry.kind == "link"}
    if dest.exists():
        for entry in ki_tree.scan(dest).entries:
            if entry.kind == "link" and aliases.get(entry.relative) != entry.target:
                raise ValueError("KI destination alias differs from the source; review before refreshing")
    rep = MaterialiseReport(dest=dest)
    dest.mkdir(parents=True, exist_ok=True)

    for entry in inventory.entries:
        if entry.kind == "link":
            continue
        rel = Path(entry.relative)
        src = ki_root / rel
        out = dest / rel
        if out.is_symlink():
            raise ValueError("Canonical KI destination entry was replaced by an alias")
        if entry.kind == "directory":
            out.mkdir(parents=True, exist_ok=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)

        # Reference cases carry hashes of portable, relative-path inputs. Their
        # bytes (including newlines and literal tokens) are part of the test
        # contract, so materialisation must not rewrite any case file.
        if rel.parts[0] == "test_cases" or src.suffix.lower() not in TEXT_SUFFIXES:
            shutil.copy2(src, out)          # binaries, PDFs, netCDF — verbatim
            rep.skipped += 1
            continue
        try:
            text = src.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            shutil.copy2(src, out)
            rep.skipped += 1
            continue

        new_text, n, unresolved = unsubstitute(text, cfg, ki_target=ki_target,
                                               server_layout=server_layout)
        if any(TOKENS[r] in new_text for r in LEAK_ROLES if r in TOKENS):
            rep.undeliverable_files += 1
            rep.undeliverable.append(str(rel))

        # Writing a real path in can break a structured file even when the
        # placeholder version parsed. A Windows path is the clear case:
        # {"p": "KISSPATH_DATA/f.nc"} becomes {"p": "C:\\Users\\foo/f.nc"},
        # and \U is not a legal JSON escape. Validate the result, mirroring the
        # guard on the porting side, so a broken file is reported rather than
        # written out silently.
        ok, why = _still_valid(out, new_text)
        if not ok and _still_valid(src, text)[0]:
            rep.corrupted.append(f"{rel}: {why}")

        # Unchanged text may carry a source-hash contract. Rewriting it with
        # platform newline translation would invalidate that contract even
        # when no paths were materialised (LF becomes CRLF on Windows).
        if new_text == text:
            shutil.copy2(src, out)
        else:
            out.write_text(new_text, encoding="utf-8")
        shutil.copystat(src, out)
        rep.files_written += 1
        rep.tokens_replaced += n
        rep.unresolved |= unresolved

    for entry in inventory.entries:
        if entry.kind != "link":
            continue
        out = dest / entry.relative
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.is_symlink():
            if out.exists():
                raise ValueError("KI alias destination is occupied by a regular entry")
            out.symlink_to(ki_copy.link_target(entry), target_is_directory=(dest / entry.target).is_dir())
        rep.skipped += 1
    if ki_tree.digest(ki_root) != source_identity:
        raise ValueError("KI source changed during materialisation")
    actual_aliases = {entry.relative: entry.target for entry in ki_tree.scan(dest).entries
                      if entry.kind == "link"}
    if actual_aliases != aliases:
        raise ValueError("KI aliases changed during materialisation")
    return rep
