"""The install manifest — ``kiss.yaml``, one per KI.

A KI describes how to *operate* a model. It does not describe how to *obtain*
one: ``dag.yaml`` carries ``repo_url``, ``language`` and ``version``, but never
a build recipe. The manifest fills exactly that gap and nothing else.

Manifests are deliberately small and declarative. Anything that cannot be
expressed here is not forced into YAML — it is handed to an agent along with
the KI's own ``diagnostics/triplets.md``, which already encodes the
error/cause/remedy knowledge for that model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

MANIFEST_VERSION = 1

#: Acquisition strategies, in rough order of how automatable they are.
STRATEGIES = ("pip", "download", "build", "wine", "bundled", "manual")


@dataclass
class Acquire:
    """How to obtain the model executable."""

    strategy: str
    #: pip
    package: str | None = None
    #: download
    url: str | None = None
    archive_member: str | None = None
    sha256: str | None = None
    #: build
    repo: str | None = None
    ref: str | None = None
    commands: list[str] = field(default_factory=list)
    system_deps: list[str] = field(default_factory=list)
    #: where the executable lands, relative to the install prefix
    produces: str | None = None
    #: wine
    exe: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Acquire":
        strategy = d.get("strategy") or "manual"
        if strategy not in STRATEGIES:
            raise ValueError(f"unknown acquire strategy {strategy!r}; expected one of {STRATEGIES}")
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class DataNeed:
    """A dataset the model needs that the repository does not ship."""

    role: str
    name: str
    why: str = ""
    url: str | None = None
    variables: list[str] = field(default_factory=list)
    optional: bool = False
    #: a path, relative to the role's root, whose presence means "satisfied"
    probe: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "DataNeed":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


#: How much of this recipe was actually observed to work, and by whom.
#:   observed   — the full recipe was executed on a clean machine and succeeded
#:   partial    — the end state was verified, but not the steps that produce it
#:   unverified — written from upstream documentation, never executed here
#:   manual     — deliberately not automatable (licence, registration, hardware)
VERIFICATION = ("observed", "partial", "unverified", "manual")


@dataclass
class Manifest:
    model: str
    binary_type: str = ""
    verified: str = "unverified"
    #: Directory name under the ``binaries`` root that this KI's hardcoded
    #: paths expect. The authoring machine used its own naming (``modflow6``,
    #: ``VIC-5.1.0``) which rarely matches the KI directory name, so installing
    #: to the wrong one produces a working binary the KI cannot find.
    install_dir: str = ""
    #: Other KI packages that must be installed first. Several models in this
    #: estate are only useful coupled — VIC produces runoff but has no routing,
    #: so its own preflight demands CaMa-Flood. Declaring it lets kiss say which
    #: model is missing instead of reporting an opaque path failure.
    depends_on: list[str] = field(default_factory=list)
    acquire: Acquire | None = None
    python_deps: list[str] = field(default_factory=list)
    system_deps: list[str] = field(default_factory=list)
    data: list[DataNeed] = field(default_factory=list)
    #: command proving the install works, run after preflight
    reference_case: str | None = None
    notes: str = ""
    #: free-text guidance handed to the agent when automation stops short
    agent_hint: str = ""

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        if yaml is None:
            raise RuntimeError("pyyaml is required to read manifests: pip install pyyaml")
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        ver = raw.get("kiss_manifest_version")
        if ver != MANIFEST_VERSION:
            raise ValueError(
                f"{path}: manifest version {ver!r}, this kiss understands {MANIFEST_VERSION}"
            )
        ver_status = raw.get("verified", "unverified")
        if ver_status not in VERIFICATION:
            raise ValueError(
                f"{path}: verified={ver_status!r}, expected one of {VERIFICATION}"
            )
        return cls(
            model=raw["model"],
            binary_type=raw.get("binary_type", ""),
            verified=ver_status,
            install_dir=raw.get("install_dir", ""),
            depends_on=list(raw.get("depends_on") or []),
            acquire=Acquire.from_dict(raw["acquire"]) if raw.get("acquire") else None,
            python_deps=list(raw.get("python_deps") or []),
            system_deps=list(raw.get("system_deps") or []),
            data=[DataNeed.from_dict(d) for d in (raw.get("data") or [])],
            reference_case=raw.get("reference_case"),
            notes=raw.get("notes", ""),
            agent_hint=raw.get("agent_hint", ""),
        )

    @classmethod
    def stub_for(cls, ki) -> "Manifest":
        """Best-effort manifest inferred from dag.yaml when none is written yet.

        This is explicitly a *starting point*, not a working recipe — it knows
        the repository and language but not how to build. ``kiss init`` will say
        so rather than pretending the install is automatic.
        """
        meta = ki.meta
        lang = (meta.get("language") or "").lower()
        strategy = "pip" if lang == "python" else "build" if meta.get("repo_url") else "manual"
        return cls(
            model=ki.name,
            verified="unverified",
            acquire=Acquire(
                strategy=strategy,
                repo=meta.get("repo_url"),
                ref=meta.get("version"),
            ),
            notes="Inferred from dag.yaml — no verified build recipe exists for this model yet.",
            agent_hint=(
                f"No hand-verified kiss.yaml exists for {ki.name}. Read SKILL.md and "
                f"dag.yaml in this KI, obtain the model from {meta.get('repo_url') or 'its home page'}, "
                "then make preflight_check.py pass. Record what worked as kiss.yaml."
            ),
        )

    @property
    def trustworthy(self) -> bool:
        """True only when the full recipe was executed and observed to succeed."""
        return self.verified == "observed"
