"""Repoint preflight checks at the user's environment.

71 of the 127 ``preflight_check.py`` files verify the model inside the
*dissection machine's* scratch tree — the throwaway venv and build directory the
KI was authored in. SimPEG is the clearest case: its only check is whether
``import SimPEG`` succeeds under
``<private-toolkit>/auto_dissect/_work/SimPEG/venv/bin/python3``. On the
authoring machine that passes; anywhere else it fails with ENOENT even when
``pip install simpeg`` has worked perfectly.

That makes preflight — the KI's verifier — report OK for one machine and FAIL
for every other, regardless of whether the model is installed. Nothing caught it
because it was only ever run where the directory existed.

These are path references, but not the *relocatable* kind the porting pass
handled. There is no user directory corresponding to "the author's build
scratch". Each reference has to be re-aimed at the equivalent thing on this
machine:

===========================  ===============================================
leaked reference             correct target
===========================  ===============================================
``…/venv/bin/python3``       ``sys.executable`` — the interpreter running us
``…/venv/…/site-packages``   ``sysconfig``'s purelib for that interpreter
``…/ki_tools_common``        the shipped shared library
``…/_work/<M>/<rel>``        ``KISSPATH_BINARIES/<M>/<rel>`` — genuinely
                             relocatable; the user *will* have a built binary,
                             just in their own install prefix
===========================  ===============================================

The last row is worth noting beyond this fix: the relative tail of each leaked
binary path is exactly the ``produces`` field an install recipe needs, recorded
by whoever originally built the model. Repairing these harvests roughly fifty
build-output paths that would otherwise have to be rediscovered by trial.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

LEAK = "KISSPATH_INTERNAL_NOT_SHIPPED"

#: A whole quoted literal that is *only* the leaked path. These are the ones
#: replaced by an expression (sys.executable), which requires the literal to be
#: consumed entirely.
_WHOLE = re.compile(rf'(?P<q>["\']){re.escape(LEAK)}(?P<tail>[^"\']*)(?P=q)')

#: The leaked path as a bare substring, wherever it appears — embedded in a
#: longer message, or split across implicitly-concatenated literals:
#:
#:     BIN_DIR = ("<LEAK>/auto_dissect_multi_agent/"
#:                "_work_v2/DayCent/...")
#:     "pip install -e <LEAK>/auto_dissect/ki_tools_common"
#:
#: Anchoring at the opening quote missed both shapes, so substring replacement
#: is used for everything that maps to another path rather than an expression.
_SUBSTRING = re.compile(rf'{re.escape(LEAK)}[A-Za-z0-9_./-]*')

#: Two adjacent quoted literals where the FIRST carries the leak token — i.e.
#: implicit concatenation splitting one path over two lines. Joined before
#: classification so the classifier sees the whole path.
_SPLIT = re.compile(
    rf'(?P<q>["\'])(?P<a>[^"\']*{re.escape(LEAK)}[^"\']*)(?P=q)\s*'
    rf'(?P=q)(?P<b>[^"\']*)(?P=q)', re.S)


#: ``…/auto_dissect[_multi_agent]/_work[_v2]/<Model>/<rest>`` — the dissection
#: scratch tree. ``<rest>`` is the build-output path within it.
_WORK = re.compile(
    r"^/auto_dissect(?:_multi_agent)?/_work(?:_v2)?/(?P<model>[^/]+)/?(?P<rest>.*)$")


@dataclass
class Fix:
    model: str
    kind: str
    before: str
    after: str


@dataclass
class UnleakResult:
    model: str
    fixes: list[Fix] = field(default_factory=list)
    produces: str = ""
    reverted: bool = False
    why: str = ""
    remaining: int = 0


def _classify(tail: str) -> tuple[str, str | None]:
    """Return (kind, replacement-expression-or-literal) for a leaked tail.

    A replacement of None means the reference could not be re-aimed and is left
    alone rather than guessed at.
    """
    if "/venv/bin/python" in tail or re.search(r"/miniconda/envs/[^/]+/bin/python", tail):
        return "interpreter", "EXPR:sys.executable"
    if "site-packages" in tail:
        return "sitepackages", 'EXPR:sysconfig.get_paths()["purelib"]'
    if "ki_tools_common" in tail:
        return "ki_tools_common", "LIT:KISSPATH_KI_TOOLS_COMMON"

    m = _WORK.match(tail)
    if m and m.group("rest"):
        return "binary", f"LIT:KISSPATH_BINARIES/{m.group('model')}/{m.group('rest')}"
    if m:
        return "binary", f"LIT:KISSPATH_BINARIES/{m.group('model')}"
    return "unmapped", None


def _ensure_imports(text: str, needed: set[str]) -> str:
    """Add any stdlib imports the replacements rely on."""
    missing = [m for m in sorted(needed)
               if not re.search(rf"^\s*import\s+{m}\b", text, re.M)]
    if not missing:
        return text
    lines = text.splitlines(keepends=True)
    # After the module docstring if there is one, else after any shebang.
    idx = 0
    if lines and lines[0].startswith("#!"):
        idx = 1
    if idx < len(lines) and lines[idx].lstrip().startswith(('"""', "'''")):
        quote = lines[idx].lstrip()[:3]
        if lines[idx].count(quote) < 2:
            idx += 1
            while idx < len(lines) and quote not in lines[idx]:
                idx += 1
        idx += 1
    block = "".join(f"import {m}\n" for m in missing)
    return "".join(lines[:idx]) + block + "".join(lines[idx:])


_SYSPATH_INSERT = re.compile(
    rf'^[ \t]*sys\.path\.insert\([^)\n]*{re.escape(LEAK)}[^)\n]*\)[ \t]*\n', re.M)


def _drop_syspath_inserts(text: str) -> tuple[str, int]:
    """Remove whole lines that put the private toolkit on sys.path."""
    new, n = _SYSPATH_INSERT.subn("", text)
    return new, n


def _parses(path: Path, text: str) -> tuple[bool, str]:
    """Validate by file type. Markdown and plain text always pass."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        try:
            ast.parse(text)
        except SyntaxError as e:
            return False, f"python line {e.lineno}"
    elif suffix in (".yaml", ".yml"):
        try:
            import yaml
            yaml.safe_load(text)
        except Exception as e:
            return False, f"yaml: {str(e)[:60]}"
    elif suffix == ".json":
        import json
        try:
            json.loads(text)
        except Exception as e:
            return False, f"json: {str(e)[:60]}"
    return True, ""


#: In a non-Python file an interpreter reference cannot become an expression:
#: writing `binary_path: sys.executable` into a YAML contract and prepending
#: `import sys` to it is how 12 format_spec.yaml files got mangled. The same
#: reference becomes the relocatable python_env placeholder instead.
_EXPR_AS_PATH = {
    "EXPR:sys.executable": "LIT:KISSPATH_PYTHON_ENV/bin/python",
    'EXPR:sysconfig.get_paths()["purelib"]': "LIT:KISSPATH_PYTHON_ENV/lib/site-packages",
}


def unleak_file(path: Path, model: str, *, dry_run: bool = False) -> UnleakResult:
    res = UnleakResult(model=model)
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as e:
        res.reverted, res.why = True, str(e)
        return res
    if LEAK not in original:
        return res

    needed: set[str] = set()

    # Pre-pass: physically join adjacent literals when the leaked path is split
    # across them, so the full path is visible to the classifier. Only runs on
    # pairs where the first fragment carries the token, so unrelated
    # concatenation elsewhere in the file is untouched.
    def _join_once(s: str) -> str:
        return _SPLIT.sub(lambda m: f"{m.group('q')}{m.group('a')}{m.group('b')}{m.group('q')}", s)

    # A sys.path.insert of the private toolkit root exists only so
    # ki_tools_common could be imported from the author's checkout. The library
    # is now installed properly, so the line is removed rather than re-aimed —
    # there is no equivalent directory to point it at.
    original_joined, dropped = _drop_syspath_inserts(original)
    for _ in range(dropped):
        res.fixes.append(Fix(model, "syspath-removed",
                             f'sys.path.insert(..., "{LEAK}/auto_dissect")',
                             "(line removed — library is installed)"))

    for _ in range(6):                     # a path split over several lines
        nxt = _join_once(original_joined)
        if nxt == original_joined:
            break
        original_joined = nxt

    is_python = path.suffix.lower() == ".py"

    def _whole(m: "re.Match") -> str:
        """Replace a literal that is entirely the leaked path."""
        tail = m.group("tail")
        kind, replacement = _classify(tail)
        if replacement is None or not replacement.startswith("EXPR:"):
            return m.group(0)          # left for the substring pass
        if not is_python:
            return m.group(0)          # handled as a path by the substring pass
        expr = replacement[5:]
        needed.add(expr.split(".")[0])
        res.fixes.append(Fix(model, kind, LEAK + tail, expr))
        return expr

    text = _WHOLE.sub(_whole, original_joined)

    def _sub(m: "re.Match") -> str:
        ref = m.group(0)
        tail = ref[len(LEAK):]
        kind, replacement = _classify(tail)
        if replacement is None:
            res.fixes.append(Fix(model, kind, ref, "(left alone)"))
            return ref
        if replacement.startswith("EXPR:"):
            # An expression cannot be spliced into a string or a data file;
            # use the path form of the same target where one exists.
            as_path = _EXPR_AS_PATH.get(replacement)
            if as_path is None:
                return ref
            replacement = as_path
        out = replacement[4:]
        if kind == "binary" and not res.produces:
            mm = _WORK.match(tail)
            if mm and mm.group("rest"):
                res.produces = mm.group("rest")
        res.fixes.append(Fix(model, kind, ref, out))
        return out

    text = _SUBSTRING.sub(_sub, text)
    if needed and is_python:
        text = _ensure_imports(text, needed)

    res.remaining = text.count(LEAK)

    # Same discipline as the porting pass: never keep an edit that breaks the
    # file — but validate it as what it actually is. Parsing a YAML contract or
    # a Markdown skill with ast.parse marked 97 healthy files "already broken
    # at line 1" and reverted every one of them.
    ok, why = _parses(path, text)
    if not ok:
        was_ok, _ = _parses(path, original)
        res.reverted = True
        res.why = (f"would not parse: {why}" if was_ok
                   else f"already broken before this change ({why})")
        return res

    if not dry_run and text != original:
        path.write_text(text, encoding="utf-8")
    return res


#: Beyond preflight_check.py, the same leaked scratch paths sit in the format
#: contract, the validation convention, the scoring scripts and prose. They are
#: the same class of reference — a build directory on the authoring machine —
#: and take the same repair.
OTHER_TARGETS = (
    "docs/format_spec.yaml",
    "docs/validation_convention.yaml",
    "knowledge_infrastructure.yaml",
    "SKILL.md",
)


def unleak_all(models_dir: Path, *, dry_run: bool = False,
               everything: bool = False) -> list[UnleakResult]:
    out: list[UnleakResult] = []
    root = Path(models_dir)
    targets: list[Path] = sorted(root.glob("*/preflight_check.py"))
    if everything:
        for rel in OTHER_TARGETS:
            targets += sorted(root.glob(f"*/{rel}"))
        for pat in ("*/run_and_score*.py", "*/tools/calib_run.py", "*/calib_run.py",
                    "*/diagnostics/*.yaml", "*/workflow/*.md", "*/docs/*.md"):
            targets += sorted(root.glob(pat))
    seen: set[Path] = set()
    for pf in targets:
        if pf in seen:
            continue
        seen.add(pf)
        model = pf.relative_to(root).parts[0]
        r = unleak_file(pf, model, dry_run=dry_run)
        if r.fixes or r.reverted:
            out.append(r)
    return out
