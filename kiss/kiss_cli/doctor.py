"""Consistency checks across every shipped KI package.

``kiss doctor`` answers one question: *if someone downloaded this package
today, what would stop them?* Every check is evidence-based — it reports what
is actually on disk, never what a registry claims.

Severities:
  BLOCK — the KI cannot work on another machine without intervention
  WARN  — it will probably work, but something is stale, noisy or misleading
  INFO  — worth knowing, not a defect
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import paths as kpaths

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

BLOCK, WARN, INFO = "BLOCK", "WARN", "INFO"

#: Artefacts every KI is expected to ship, and whether absence is fatal.
EXPECTED = [
    ("SKILL.md", BLOCK, "the agent-facing operating instructions"),
    ("preflight_check.py", BLOCK, "the environment verifier"),
    ("dag.yaml", WARN, "the machine-readable model descriptor"),
    ("docs/format_spec.yaml", WARN, "input/output format contract"),
]

#: Frameworks with no simulation semantics — a missing dag.yaml is correct here.
DAG_EXEMPT = {"BMI", "ESMF", "PyMT"}

DAG_REQUIRED_KEYS = {
    "template_version", "identity", "boundary", "inputs",
    "outputs", "states", "processes", "influence", "safety",
}
DAG_CURRENT_VERSION = "3.5"

SECRET_RE = re.compile(
    r"(sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|"
    r"(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{12,}['\"])",
    re.IGNORECASE,
)

TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".sh", ".txt", ".cfg", ".ini", ".json", ".toml"}


@dataclass
class Finding:
    ki: str
    severity: str
    check: str
    detail: str
    count: int = 1

    def __str__(self) -> str:  # pragma: no cover - display only
        n = f" ({self.count})" if self.count > 1 else ""
        return f"{self.severity:<5} {self.ki:<22} {self.check:<22} {self.detail}{n}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    checked: int = 0

    def add(self, *a, **kw) -> None:
        self.findings.append(Finding(*a, **kw))

    def by_severity(self, sev: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == sev]

    def by_check(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.check, []).append(f)
        return out

    def blocked_kis(self) -> set[str]:
        return {f.ki for f in self.findings if f.severity == BLOCK}


def check_ki(ki) -> list[Finding]:
    """Run every consistency check against a single KI package."""
    out: list[Finding] = []
    add = lambda sev, check, detail, count=1: out.append(  # noqa: E731
        Finding(ki.name, sev, check, detail, count)
    )

    # 1. Required artefacts -------------------------------------------------
    for rel, sev, why in EXPECTED:
        if not (ki.root / rel).exists():
            if rel == "dag.yaml" and ki.name in DAG_EXEMPT:
                add(INFO, "artefact-exempt", f"no dag.yaml — {ki.name} is a framework, not a model")
            else:
                add(sev, "artefact-missing", f"{rel} absent ({why})")

    # 2. dag.yaml schema ----------------------------------------------------
    if ki.dag and yaml is not None:
        try:
            doc = yaml.safe_load(ki.dag.read_text(encoding="utf-8", errors="replace")) or {}
        except Exception as e:
            add(BLOCK, "dag-unparseable", f"dag.yaml does not parse: {str(e)[:80]}")
            doc = None
        if doc is not None:
            missing = DAG_REQUIRED_KEYS - set(doc)
            extra = set(doc) - DAG_REQUIRED_KEYS
            if missing:
                add(BLOCK, "dag-schema", f"missing top-level keys: {sorted(missing)}")
            if extra:
                add(WARN, "dag-schema", f"unexpected top-level keys: {sorted(extra)}")
            ver = str(doc.get("template_version"))
            if ver != DAG_CURRENT_VERSION:
                add(WARN, "dag-version", f"template_version {ver}, current is {DAG_CURRENT_VERSION}")
            ident = doc.get("identity") or {}
            mid = ident.get("model_id")
            if mid and _norm(mid) != _norm(ki.name):
                add(WARN, "identity-mismatch", f"dag model_id {mid!r} != directory {ki.name!r}")
            if not ident.get("repo_url"):
                add(WARN, "no-source", "identity.repo_url absent — installer cannot locate the source")

    # 3. Portability --------------------------------------------------------
    port = ki.portability
    if port.total:
        roles = ", ".join(f"{r}×{port.by_role[r]}" for r in sorted(port.by_role))
        add(BLOCK, "hardcoded-paths", f"{port.total} authoring-machine paths in "
            f"{len(port.files)} files [{roles}]", port.total)
    for role, n in port.leaks.items():
        add(WARN, "internal-leak", f"{n} refs to private tooling ({role}) leaked into a public package", n)

    # 4. Shipped noise ------------------------------------------------------
    baks = [p for p in ki.root.rglob("*") if p.is_file() and
            (p.suffix in (".bak", ".bak2") or ".bak" in p.name)]
    if baks:
        add(WARN, "backup-files", f"{len(baks)} .bak files shipped", len(baks))

    # 5. Python validity ----------------------------------------------------
    broken = []
    for py in ki.root.rglob("*.py"):
        try:
            ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            broken.append(f"{py.relative_to(ki.root)}:{e.lineno}")
        except OSError:
            pass
    if broken:
        add(BLOCK, "python-syntax", f"{len(broken)} files fail to parse: {broken[0]}"
            + (" …" if len(broken) > 1 else ""), len(broken))

    # 6. Undeclared dependency on ki_tools_common ---------------------------
    uses_common = any(
        "ki_tools_common" in p.read_text(encoding="utf-8", errors="replace")
        for p in ki.root.rglob("*.py") if p.is_file()
    ) if any(ki.root.rglob("*.py")) else False
    if uses_common:
        add(INFO, "needs-ki-tools-common", "imports ki_tools_common (must be installed separately)")

    # 7. SKILL.md pointing at files that are not here -----------------------
    if ki.skill:
        text = ki.skill.read_text(encoding="utf-8", errors="replace")
        dangling = []
        for m in re.finditer(r"`([\w./-]+\.(?:py|md|yaml|yml))`", text):
            rel = m.group(1).lstrip("./")
            if rel.startswith(("http", "/")):
                continue
            if not (ki.root / rel).exists() and "/" in rel:
                dangling.append(rel)
        uniq = sorted(set(dangling))
        if uniq:
            add(WARN, "dangling-ref", f"SKILL.md cites {len(uniq)} missing files: {uniq[0]}"
                + (" …" if len(uniq) > 1 else ""), len(uniq))

    # 8. Secrets ------------------------------------------------------------
    for f in ki.root.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if SECRET_RE.search(f.read_text(encoding="utf-8", errors="replace")):
                add(BLOCK, "possible-secret", f"credential-shaped string in {f.relative_to(ki.root)}")
        except OSError:
            pass

    # 9. Install manifest ---------------------------------------------------
    # A manifest may live inside the KI (kiss.yaml) or in the repository's
    # shared manifests directory; either counts.
    shipped = ki.root.parent.parent / "kiss" / "manifests" / f"{ki.name}.yaml"
    if not ki.manifest and not shipped.exists():
        add(WARN, "no-manifest", "no kiss.yaml — install cannot be automated, agent must improvise")

    return out


def run(catalog) -> Report:
    rep = Report()
    for ki in catalog:
        rep.checked += 1
        rep.findings.extend(check_ki(ki))
    return rep


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower().replace("+", "plus"))
