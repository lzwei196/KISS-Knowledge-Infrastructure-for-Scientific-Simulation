"""What an agent operating this KI is allowed to touch.

A KI is a *declaration* of what a model needs: the manifest names the binary,
the install directory and the data roles; the package itself is the tool
library. That declaration is exactly the input a least-privilege policy wants,
which is why KISS can grant up front instead of interrogating the user on every
command — the thing neither Pi nor DeepSeek Harness can do, because a general
coding agent cannot know in advance what a command will need.

Two rules are borrowed from DeepSeek Harness's approval seam, and both matter
more than they look:

* **Fail closed.** A decision is honoured only when it is an explicit allow.
  A missing, malformed or crashed decision path denies. A bug in the approval
  UI must shut the gate, never open it.
* **Grants are specific.** An allow covers the thing that was asked about, not
  a category. Escalating to "allow everything" is a separate, named, deliberate
  act — Codex and DeepSeek both call that mode ``danger-full-access``, and this
  module keeps the name because the honesty is the point.

Backends differ in what they can enforce (see :class:`Enforcement`). The policy
is expressed once, here, and each backend reports how faithfully it applied it.
Where a backend cannot honour least privilege, KISS says so rather than
implying a guarantee it did not obtain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

POLICY_FILE = "kiss-policy.json"


class Posture(str, Enum):
    """How much the agent may do before anyone is asked."""

    #: Grant exactly what the KI declares; deny and ask for anything else.
    LEAST_PRIVILEGE = "least-privilege"
    #: As above, plus unrestricted freedom inside the model's own workdir.
    WORKSPACE_WRITE = "workspace-write"
    #: No restriction at all. Named, never defaulted, always reported.
    DANGER_FULL_ACCESS = "danger-full-access"


class Enforcement(str, Enum):
    """How faithfully a backend applied the policy. Reported, never assumed."""

    #: Per-tool, per-path grants — the policy was applied as written.
    EXACT = "exact"
    #: Mapped onto coarser native modes; the shape is right, the edges are not.
    APPROXIMATE = "approximate"
    #: The backend has only on/off. Least privilege was NOT achieved.
    NONE = "none"


@dataclass
class Grant:
    """One thing the agent may do, and why it was granted."""

    kind: str          # "read" | "write" | "exec" | "network"
    path: str
    reason: str = ""

    def key(self) -> str:
        return f"{self.kind}:{self.path}"


@dataclass
class Policy:
    """The complete set of grants for one KI in one workdir."""

    model: str
    posture: Posture = Posture.LEAST_PRIVILEGE
    grants: list[Grant] = field(default_factory=list)
    #: Grants the user approved after an earlier denial, persisted per workdir.
    approved: list[Grant] = field(default_factory=list)

    # --- construction ------------------------------------------------------
    @classmethod
    def derive(cls, ki, man, cfg, *, posture: Posture = Posture.LEAST_PRIVILEGE) -> "Policy":
        """Build the policy from what the KI and its manifest declare."""
        p = cls(model=ki.name, posture=posture)

        # The package itself: readable, and its tools executable. Without this
        # the agent cannot read SKILL.md, which is the one thing it must do.
        p.add("read", ki.root, "the KI package — SKILL.md, dag.yaml, diagnostics")
        p.add("exec", ki.root, "validated tools shipped with this KI")

        # The workdir is the model's own scratch space.
        p.add("read", cfg.root, "this model's working directory")
        p.add("write", cfg.root, "outputs, logs and scratch belong here")

        # The binary the manifest promises to produce.
        prefix = cfg.roles["binaries"] / (man.install_dir or ki.name)
        p.add("exec", prefix, f"the {ki.name} executable and its install tree")
        p.add("read", prefix, "model support files alongside the binary")

        # Interpreter, so Python-based KIs can run at all.  Grant the exact
        # configured spelling even when it is a command name: native agent
        # CLIs match ``Bash(python3:*)`` separately from filesystem grants.
        configured_python = str(cfg.python or "").strip()
        if configured_python:
            p.add("exec", configured_python, "the configured KI Python interpreter")
        interp = Path(configured_python) if configured_python else Path()
        if interp.is_absolute():
            env_root = interp.parent.parent if interp.parent.name == "bin" else interp.parent
            p.add("exec", env_root, "the interpreter this model was installed into")
            p.add("read", env_root, "site-packages for this model's dependencies")

        # A declared runtime such as Wine is part of operating the model, not
        # an unexpected shell escape.  Setup used to grant build tools while a
        # normal verified project chat forgot the runtime itself.
        for command in man.system_deps:
            if str(command).strip():
                p.add("exec", command, f"declared {ki.name} runtime dependency")

        # Declared data needs — read-only. A model reads forcing; it does not
        # rewrite the archive it came from.
        for need in man.data:
            base = cfg.roles.get(need.role)
            if base is not None:
                p.add("read", base, f"declared input: {need.name}")

        p.add("write", cfg.roles["outputs"], "declared output location")
        p.add_authoring_aliases(cfg)
        return p

    def add(self, kind: str, path, reason: str = "") -> None:
        value = str(path) if kind == "network" else str(Path(path))
        g = Grant(kind=kind, path=value, reason=reason)
        if not any(x.key() == g.key() for x in self.grants):
            self.grants.append(g)

    def add_authoring_aliases(self, cfg) -> None:
        """Also grant each path under the name the agent will actually see.

        The agent runs inside the relocation namespace, where this KI's
        directories appear at the *authoring* machine's paths. A grant written
        only in host terms therefore never matches: the agent asks to run
        ``/mnt/disk1/.../model/modflow6/bin/mf6`` while the allowlist mentions
        ``~/kiss/modflow6/binaries/modflow6``. Both spellings name the same
        bytes, so both must be granted.
        """
        from .paths import LEAK_ROLES, LEGACY_PREFIXES

        aliases: list[Grant] = []
        for g in list(self.grants):
            host = Path(g.path)
            for prefix, role in LEGACY_PREFIXES:
                if role in LEAK_ROLES:
                    continue
                base = cfg.roles.get(role)
                if base is None:
                    continue
                try:
                    rel = host.relative_to(base)
                except ValueError:
                    continue
                alias = str(Path(prefix) / rel) if str(rel) != "." else prefix
                if not any(x.key() == f"{g.kind}:{alias}" for x in self.grants + aliases):
                    aliases.append(Grant(g.kind, alias, f"{g.reason} (as seen in the namespace)"))
                break
        self.grants.extend(aliases)

    # --- evaluation --------------------------------------------------------
    def all_grants(self) -> list[Grant]:
        return [*self.grants, *self.approved]

    def allows(self, kind: str, target: str | Path) -> bool:
        """Whether ``target`` is covered. Prefix match on resolved paths."""
        if self.posture is Posture.DANGER_FULL_ACCESS:
            return True
        try:
            t = str(Path(target).resolve())
        except OSError:
            return False
        for g in self.all_grants():
            if g.kind != kind:
                continue
            base = g.path
            if t == base or t.startswith(base.rstrip("/") + "/"):
                return True
        return False

    def approve(self, kind: str, path, reason: str = "approved by the user") -> Grant:
        """Record a user decision. Only ever widens, never silently."""
        value = str(path) if kind == "network" else str(Path(path))
        g = Grant(kind=kind, path=value, reason=reason)
        if not any(x.key() == g.key() for x in self.approved):
            self.approved.append(g)
        return g

    # --- persistence -------------------------------------------------------
    def save(self, workdir: Path) -> Path:
        f = Path(workdir) / POLICY_FILE
        f.write_text(json.dumps({
            "model": self.model,
            "posture": self.posture.value,
            "approved": [g.__dict__ for g in self.approved],
        }, indent=2), encoding="utf-8")
        return f

    @classmethod
    def load_approved(cls, workdir: Path) -> tuple[Posture | None, list[Grant]]:
        """Read back the user's persisted decisions for this workdir."""
        f = Path(workdir) / POLICY_FILE
        if not f.is_file():
            return None, []
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Fail closed: an unreadable policy grants nothing extra.
            return None, []
        posture = None
        try:
            posture = Posture(raw.get("posture"))
        except ValueError:
            posture = None
        return posture, [Grant(**g) for g in raw.get("approved", []) if isinstance(g, dict)]


# --- backend mapping --------------------------------------------------------

def claude_args(pol: Policy) -> tuple[list[str], Enforcement]:
    """Claude Code takes per-tool, per-path grants, so the policy maps exactly."""
    if pol.posture is Posture.DANGER_FULL_ACCESS:
        return ["--permission-mode", "bypassPermissions"], Enforcement.NONE

    tools: list[str] = []
    for g in pol.all_grants():
        d = f"{g.path.rstrip('/')}/**"
        if g.kind == "read":
            tools += [f"Read({d})", f"Glob({d})", f"Grep({d})"]
        elif g.kind == "write":
            tools += [f"Write({d})", f"Edit({d})"]
        elif g.kind == "exec":
            # Setup also grants specific build commands ("git", "cmake", …).
            # Claude's Bash permission grammar treats those as command
            # patterns, while executable trees remain filesystem patterns.
            path = Path(g.path)
            if not path.is_absolute() and "/" not in g.path:
                tools.append(f"Bash({g.path}:*)")
            elif path.is_file():
                tools.append(f"Bash({g.path}:*)")
            else:
                tools.append(f"Bash({g.path.rstrip('/')}/**)")
    # Deduplicate, keep order stable so the argv is reproducible.
    seen, uniq = set(), []
    for t in tools:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return ["--allowedTools", *uniq], Enforcement.EXACT


def codex_args(pol: Policy) -> tuple[list[str], Enforcement]:
    """Codex offers three OS sandbox modes — the right shape, coarser edges."""
    if pol.posture is Posture.DANGER_FULL_ACCESS:
        return ["--sandbox", "danger-full-access"], Enforcement.NONE
    # workspace-write is the closest native fit: writes confined to the work
    # tree, reads broader than we asked for. Network remains off unless the
    # user explicitly approved it for this project through a structured
    # GeoForge handoff. Codex exposes network as a workspace-write setting,
    # not as part of its --sandbox flag.
    args = ["--sandbox", "workspace-write"]
    if any(grant.kind == "network" for grant in pol.all_grants()):
        args += ["-c", "sandbox_workspace_write.network_access=true"]
    return args, Enforcement.APPROXIMATE


def coarse_args(pol: Policy) -> tuple[list[str], Enforcement]:
    """Kimi, Gemini and Qwen expose only an all-or-nothing auto-approve.

    There is no way to express "these paths and no others", so least privilege
    is not achievable. Returning NONE makes the caller say so out loud.
    """
    if pol.posture is Posture.DANGER_FULL_ACCESS:
        return ["--yolo"], Enforcement.NONE
    return [], Enforcement.NONE


def describe(enforcement: Enforcement, backend: str) -> str:
    """One honest sentence about what was actually enforced."""
    if enforcement is Enforcement.EXACT:
        return f"{backend}: least-privilege applied as written."
    if enforcement is Enforcement.APPROXIMATE:
        return (f"{backend}: mapped onto its native sandbox modes — writes are "
                "confined to the work tree, but reads are broader than the policy asks.")
    return (f"{backend}: offers no per-path permissions, so the policy could NOT "
            "be enforced. It runs with your full user rights.")
