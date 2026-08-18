"""Work out how to install a model, instead of shipping 127 hand-written recipes.

A KI says what a model *is* — repo, version, language, what it simulates. It
never says how to *build* it. Writing that gap out by hand 127 times is the
wrong shape of work: it cannot be verified without actually building each one,
and a recipe nobody has run is a guess with a version number.

So this module gathers the evidence and hands it to an agent, which proposes a
recipe that KISS then *executes*. Nothing is recorded as working on the strength
of a proposal.

Evidence is gathered in order of how much it can be trusted:

  1. **Dockerfile / CI workflow** — a build that provably runs, re-verified by
     upstream on every commit. Measured across this repository: 39 of the 61
     compiled models hosted on GitHub have one.
  2. **CMakeLists / configure** — the build system is known, the flags are not.
  3. **README / INSTALL** — a claim about how to build, which drifts.
  4. **The KI's own harvested build output** — where the binary landed when
     somebody last built this model, recovered from the preflight checks.
  5. **The official page** — for licensed or registration-walled models this is
     the honest answer, not a fallback. APEX and DSSAT are never going to be
     `pip install`-able.

The human's part is deliberately small and always machine-checkable: install a
toolchain (once per machine, not once per model), accept a licence, drop a file
somewhere. "I did it" is never taken on trust — the check is re-run.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

RAW = "https://raw.githubusercontent.com/{repo}/HEAD/{path}"
TREE = "https://api.github.com/repos/{repo}/git/trees/HEAD?recursive=1"

#: Files worth reading, most trustworthy first. The ordering is the point:
#: a Dockerfile is executable truth, a README is a claim.
EVIDENCE_ORDER = [
    ("docker", re.compile(r"(^|/)Dockerfile[^/]*$", re.I)),
    ("ci", re.compile(r"^\.github/workflows/.*\.ya?ml$", re.I)),
    ("cmake", re.compile(r"^CMakeLists\.txt$")),
    ("autotools", re.compile(r"^(configure(\.ac)?|Makefile\.am)$")),
    ("make", re.compile(r"^(GNUm|M)akefile$")),
    ("readme", re.compile(r"^(README|INSTALL|BUILD)[^/]*$", re.I)),
]

MAX_BYTES = 12000


@dataclass
class Evidence:
    kind: str
    path: str
    text: str = ""

    def excerpt(self, limit: int = MAX_BYTES) -> str:
        return self.text[:limit]


@dataclass
class Research:
    model: str
    repo: str | None = None
    ref: str | None = None
    produces: str | None = None
    language: str | None = None
    official: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def strength(self) -> str:
        kinds = {e.kind for e in self.evidence}
        if kinds & {"docker", "ci"}:
            return "strong"          # a build upstream actually runs
        if kinds & {"cmake", "autotools", "make"}:
            return "medium"          # build system known, flags unknown
        if kinds:
            return "weak"            # prose only
        return "none"


def _github_repo(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"github\.com/([^/\s#?]+/[^/\s#?]+)", url)
    return m.group(1).rstrip(".git") if m else None


def _fetch(url: str, timeout: int = 25) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "kiss-recipe"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def gather(ki, harvested: dict | None = None, *, max_files: int = 6) -> Research:
    """Collect everything known about how to build this model."""
    meta = ki.meta or {}
    res = Research(
        model=ki.name,
        ref=meta.get("version"),
        language=meta.get("language"),
        official=meta.get("repo_url"),
        produces=(harvested or {}).get(ki.name),
    )
    res.repo = _github_repo(meta.get("repo_url"))

    if not res.repo:
        res.notes.append(
            "No GitHub repository. The official page above is where a human has "
            "to go — for a licensed or registration-walled model that is the "
            "correct answer, not a failure.")
        return res

    listing = _fetch(TREE.format(repo=res.repo))
    if not listing:
        res.notes.append(f"Could not list {res.repo} (network, rate limit, or private).")
        return res
    try:
        paths = [n["path"] for n in json.loads(listing).get("tree", []) if n.get("type") == "blob"]
    except (json.JSONDecodeError, KeyError):
        res.notes.append("Repository listing was not parseable.")
        return res

    picked: list[tuple[str, str]] = []
    for kind, pat in EVIDENCE_ORDER:
        for p in paths:
            if pat.search(p) and len(picked) < max_files:
                picked.append((kind, p))
                break                      # one file per kind is enough context

    for kind, p in picked:
        text = _fetch(RAW.format(repo=res.repo, path=p))
        if text:
            res.evidence.append(Evidence(kind=kind, path=p, text=text))

    if not res.evidence:
        res.notes.append("Repository has no recognisable build files.")
    return res


def brief(res: Research, ki) -> str:
    """The research brief handed to the agent."""
    out: list[str] = [
        f"Work out how to build and install **{res.model}** on this machine.",
        "",
        "[WHAT THE KI KNOWS]",
        f"  language   {res.language or 'unknown'}",
        f"  source     {res.official or 'unknown'}",
        f"  version    {res.ref or 'unspecified — pick the newest stable tag'}",
    ]
    if res.produces:
        out.append(f"  build output  {res.produces}")
        out.append("     ^ recovered from this KI's own preflight: where the binary")
        out.append("       landed when somebody last built this model. Trust it over a guess.")
    out += ["", f"[UPSTREAM BUILD EVIDENCE — {res.strength()}]"]

    if not res.evidence:
        out.append("  none found.")
    for e in res.evidence:
        label = {"docker": "Dockerfile — a build that actually runs",
                 "ci": "CI workflow — re-verified by upstream on every commit",
                 "cmake": "CMake — build system known, flags are not",
                 "autotools": "autotools", "make": "Makefile",
                 "readme": "prose — a claim about the build, may have drifted"}.get(e.kind, e.kind)
        out += ["", f"--- {e.path}  ({label})", "```", e.excerpt(), "```"]

    for n in res.notes:
        out += ["", f"NOTE: {n}"]

    out += [
        "",
        "[WHAT TO PRODUCE]",
        "A kiss.yaml manifest. Prefer transcribing the Dockerfile or CI build over",
        "inventing one — those are verified by upstream, a README is not.",
        "",
        "```yaml",
        "kiss_manifest_version: 1",
        f"model: {res.model}",
        "verified: unverified        # kiss sets this to observed only after it runs",
        f"install_dir: {res.model}",
        "acquire:",
        "  strategy: build           # pip | download | build | wine | manual",
        f"  repo: {res.official or '<url>'}",
        f"  ref: \"{res.ref or '<tag>'}\"",
        "  commands:",
        "    - <build commands, in order>",
        f"  produces: {res.produces or '<path to the binary, relative to the checkout>'}",
        "  system_deps: [<packages needing sudo — these are the human's job>]",
        "```",
        "",
        "[RULES]",
        "1. Do NOT claim a recipe works. kiss will run it and check preflight.",
        "2. Put anything needing sudo in system_deps rather than in commands —",
        "   a toolchain is installed once per machine, not once per model, and",
        "   the agent has no authority to install it.",
        "3. If the model is licensed or requires registration, use",
        "   strategy: manual and say exactly which page the user must visit and",
        "   where to put the file. That is a correct answer, not a failure.",
        "4. Pin the ref. An unpinned build is not reproducible.",
    ]
    return "\n".join(out)


def verify(model: str, manifest_path: Path, models_dir: Path, workdir: Path,
           python: str | None = None) -> tuple[bool, str]:
    """Run the proposed recipe for real. This is what `observed` means."""
    cmd = [python or "python3", "-m", "kiss_cli", "--models", str(models_dir),
           "init", model, "-w", str(workdir)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        return False, "install exceeded one hour"
    out = p.stdout + p.stderr
    ok = bool(re.search(r"preflight\s*\.*\s*ok", out))
    return ok, out[-4000:]
