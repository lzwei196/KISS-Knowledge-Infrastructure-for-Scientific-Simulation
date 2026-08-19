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
    # Launch the installer the same way this process was launched. Running
    # "python -m kiss_cli" with no path only worked when the caller happened to
    # sit in the checkout: from anywhere else it died with "No module named
    # kiss_cli", and the loop read that as the recipe being wrong and discarded
    # a manifest the agent had got right. A frozen app has no importable
    # package at all, so there it re-invokes its own binary.
    import os
    import sys as _sys

    pkg_parent = Path(__file__).resolve().parent.parent
    env = {**os.environ}
    if getattr(_sys, "frozen", False):
        cmd = [_sys.executable]
    else:
        cmd = [python or _sys.executable or "python3", "-m", "kiss_cli"]
        env["PYTHONPATH"] = os.pathsep.join(
            [str(pkg_parent)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    cmd += ["--models", str(models_dir), "init", model, "-w", str(workdir)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600,
                           cwd=str(pkg_parent), env=env)
    except subprocess.TimeoutExpired:
        return False, "install exceeded one hour"
    out = p.stdout + p.stderr
    ok = bool(re.search(r"preflight\s*\.*\s*ok", out))
    return ok, out[-4000:]


# --- the loop: propose -> verify -> record ----------------------------------

MANIFEST_RE = re.compile(r"```(?:ya?ml)?\s*\n(.*?)```", re.S)


def extract_manifest(reply: str) -> str | None:
    """Pull a manifest out of an agent's reply.

    Agents wrap YAML in fences and often add prose either side. Take the first
    fenced block that looks like a manifest; fall back to the whole reply if it
    is bare YAML.
    """
    for block in MANIFEST_RE.findall(reply):
        if "kiss_manifest_version" in block:
            return block.strip()
    return reply.strip() if "kiss_manifest_version" in reply else None


def validate_manifest(text: str, model: str) -> tuple[dict | None, str]:
    """Parse and sanity-check a proposed manifest before anything runs it."""
    try:
        import yaml
        data = yaml.safe_load(text)
    except Exception as e:
        return None, f"not valid YAML: {str(e)[:120]}"
    if not isinstance(data, dict):
        return None, "manifest is not a mapping"
    if data.get("kiss_manifest_version") != 1:
        return None, "missing or wrong kiss_manifest_version"
    if data.get("model") != model:
        return None, f"manifest is for {data.get('model')!r}, not {model!r}"
    acq = data.get("acquire") or {}
    if acq.get("strategy") not in ("pip", "download", "build", "wine", "bundled", "manual"):
        return None, f"unknown acquire strategy {acq.get('strategy')!r}"
    # The agent proposes; only a passing preflight may claim otherwise.
    data["verified"] = "unverified"
    return data, ""


def propose_and_verify(ki, harvested, models_dir: Path, workdir: Path,
                       manifests_dir: Path, run_agent, emit,
                       python: str | None = None) -> bool:
    """Discover a build recipe, have an agent write it, then prove it.

    ``run_agent(prompt) -> str`` is injected so this works with whichever
    driver the session uses. Nothing is recorded on the agent's say-so: the
    manifest is written to a temp file, `kiss init` runs it for real, and only
    a passing preflight promotes it to `verified: observed`.
    """
    import tempfile

    import yaml

    emit(f"[1/4] gathering build evidence for {ki.name}…\n")
    res = gather(ki, harvested)
    emit(f"      repo={res.repo or 'none'}  evidence={res.strength()}"
         f"  files={[e.path for e in res.evidence]}\n")
    if res.strength() == "none" and not res.official:
        emit("      no source and no evidence — this model needs a human "
             "(licence or registration). Nothing to propose.\n")
        return False

    emit("[2/4] asking the agent to write a manifest from that evidence…\n")
    reply = run_agent(brief(res, ki))
    text = extract_manifest(reply or "")
    if not text:
        emit("      the agent did not return a manifest block.\n")
        return False

    data, why = validate_manifest(text, ki.name)
    if data is None:
        emit(f"      proposal rejected: {why}\n")
        return False
    emit(f"      proposed: strategy={data['acquire'].get('strategy')}"
         f" ref={data['acquire'].get('ref')}"
         f" produces={data['acquire'].get('produces')}\n")

    emit("[3/4] running it for real — a proposal is not a recipe…\n")
    with tempfile.TemporaryDirectory() as td:
        cand = Path(td) / f"{ki.name}.yaml"
        cand.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        staged = manifests_dir / f"{ki.name}.yaml"
        backup = staged.read_text(encoding="utf-8") if staged.exists() else None
        manifests_dir.mkdir(parents=True, exist_ok=True)
        staged.write_text(cand.read_text(encoding="utf-8"), encoding="utf-8")
        ok, log = verify(ki.name, staged, models_dir, workdir, python)
        if not ok:
            # Leave the tree as it was: an unproven recipe must not linger and
            # look official.
            if backup is None:
                staged.unlink(missing_ok=True)
            else:
                staged.write_text(backup, encoding="utf-8")
            emit("      install did NOT reach a passing preflight. Recipe discarded.\n")
            for line in log.strip().splitlines()[-12:]:
                emit(f"      {line}\n")
            return False

    data["verified"] = "observed"
    data["notes"] = (f"OBSERVED: proposed by agent from {res.strength()} upstream "
                     f"evidence ({', '.join(e.kind for e in res.evidence) or 'none'}), "
                     f"then executed by kiss init to a passing preflight.")
    staged.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    emit(f"[4/4] verified and recorded -> {staged}\n")
    return True
