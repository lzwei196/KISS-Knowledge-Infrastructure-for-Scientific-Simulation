"""Discovery: turn the ``models/`` tree into a queryable catalogue.

The repository ships 127 KI packages. 124 of them carry a ``dag.yaml`` on a
shared 9-key schema, and every one carries ``SKILL.md``, ``preflight_check.py``
and ``docs/format_spec.yaml``. That is enough structure to enumerate what is
installable without any hand-maintained index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from . import paths as kpaths

try:
    import yaml
except ImportError:  # pragma: no cover - surfaced by cli with a clear message
    yaml = None


@dataclass
class KI:
    """One knowledge-infrastructure package on disk."""

    name: str
    root: Path

    # --- shipped artefacts -------------------------------------------------
    @property
    def skill(self) -> Path | None:
        return self._maybe("SKILL.md")

    @property
    def dag(self) -> Path | None:
        return self._maybe("dag.yaml")

    @property
    def preflight(self) -> Path | None:
        return self._maybe("preflight_check.py")

    @property
    def triplets(self) -> Path | None:
        for cand in ("diagnostics/triplets.md", "diagnostics/triplets.yaml"):
            p = self._maybe(cand)
            if p:
                return p
        return None

    @property
    def format_spec(self) -> Path | None:
        return self._maybe("docs/format_spec.yaml")

    @property
    def manifest(self) -> Path | None:
        return self._maybe("kiss.yaml")

    def _maybe(self, rel: str) -> Path | None:
        p = self.root / rel
        return p if p.exists() else None

    # --- parsed metadata ---------------------------------------------------
    @cached_property
    def meta(self) -> dict:
        """``identity`` block from dag.yaml, plus a few derived fields."""
        if not self.dag or yaml is None:
            return {}
        try:
            doc = yaml.safe_load(self.dag.read_text(encoding="utf-8", errors="replace")) or {}
        except Exception:
            return {}
        ident = doc.get("identity") or {}
        impl = ident.get("implementation") or {}
        return {
            "model_id": ident.get("model_id") or self.name,
            "language": ident.get("language"),
            "license": ident.get("license"),
            "repo_url": ident.get("repo_url"),
            "version": impl.get("version"),
            "impl_id": impl.get("id"),
            "ki_class": ident.get("ki_class"),
            "reference": ident.get("scientific_reference_version"),
            "spatial": (doc.get("boundary") or {}).get("spatial"),
            "temporal": (doc.get("boundary") or {}).get("temporal"),
        }

    @cached_property
    def forcing_vars(self) -> list[str]:
        """Names of the atmospheric/forcing inputs the model requires."""
        if not self.dag or yaml is None:
            return []
        try:
            doc = yaml.safe_load(self.dag.read_text(encoding="utf-8", errors="replace")) or {}
        except Exception:
            return []
        out = []
        for item in ((doc.get("inputs") or {}).get("forcing") or []):
            if isinstance(item, dict) and item.get("name"):
                out.append(str(item["name"]))
        return out

    # --- portability -------------------------------------------------------
    @cached_property
    def portability(self) -> "Portability":
        return Portability.scan(self)

    def __str__(self) -> str:  # pragma: no cover - display only
        return self.name


@dataclass
class Portability:
    """What stands between this KI and running on someone else's machine."""

    ki_name: str
    by_role: dict[str, int] = field(default_factory=dict)
    files: dict[str, int] = field(default_factory=dict)
    leaks: dict[str, int] = field(default_factory=dict)

    TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".sh", ".txt", ".cfg", ".ini", ".json", ".toml"}

    @classmethod
    def scan(cls, ki: KI) -> "Portability":
        p = cls(ki_name=ki.name)
        for f in ki.root.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in cls.TEXT_SUFFIXES:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            hits = kpaths.scan_text(text)
            if not hits:
                continue
            rel = str(f.relative_to(ki.root))
            p.files[rel] = len(hits)
            for _, role in hits:
                if role in kpaths.LEAK_ROLES:
                    p.leaks[role] = p.leaks.get(role, 0) + 1
                else:
                    p.by_role[role] = p.by_role.get(role, 0) + 1
        return p

    @property
    def total(self) -> int:
        return sum(self.by_role.values())

    @property
    def clean(self) -> bool:
        return self.total == 0 and not self.leaks

    @property
    def roles_needed(self) -> list[str]:
        return sorted(r for r in self.by_role if r in kpaths.USER_ROLES)


class Catalog:
    """The set of KI packages under a ``models/`` directory.

    A second, writable root holds user-imported KIs. The bundled root inside a
    frozen app is read-only, so "import" has to live somewhere else; a name
    collision resolves to the bundled package and the import is rejected,
    because silently shadowing a curated KI with an uploaded one would be a
    substitution the user never sees.
    """

    def __init__(self, models_dir: Path, user_dir: Path | None = None):
        self.models_dir = Path(models_dir).resolve()
        self.user_dir = Path(user_dir).resolve() if user_dir else None
        if not self.models_dir.is_dir():
            raise NotADirectoryError(f"no models directory at {self.models_dir}")

    @classmethod
    def discover(cls, start: Path | None = None) -> "Catalog":
        """Find the ``models/`` directory of KI packages.

        Tried in order: upward from ``start``/cwd (a repo checkout), then next
        to the executable itself — a frozen desktop binary is usually launched
        from wherever the browser saved it, with ``kiss-ki-packages.tar.gz``
        extracted alongside, and cwd is some unrelated home directory — then
        ``~/kiss``. The error message carries the fix, because the person who
        sees it has just downloaded a binary and has no README in front of them.
        """
        import sys

        roots: list[Path] = []
        here = Path(start or Path.cwd()).resolve()
        roots += [here, *here.parents]
        if getattr(sys, "frozen", False):
            # Data bundled into the app (--add-data "models:models") lands at
            # sys._MEIPASS — the first place a self-contained build should look.
            mp = getattr(sys, "_MEIPASS", None)
            if mp:
                roots.append(Path(mp))
            exe = Path(sys.executable).resolve().parent
            roots += [exe, *exe.parents]
        roots.append(Path.home() / "kiss")
        try:
            from .firstrun import data_dir
            roots.append(data_dir())
        except Exception:
            pass

        seen = set()
        for cand in roots:
            if cand in seen:
                continue
            seen.add(cand)
            m = cand / "models"
            if m.is_dir() and any(m.glob("*/SKILL.md")):
                return cls(m)
        raise FileNotFoundError(
            "could not find the KI packages (a models/ directory with SKILL.md "
            "files). Download kiss-ki-packages.tar.gz from the release, extract "
            "it next to this app (tar xzf kiss-ki-packages.tar.gz), and launch "
            "again — or pass --models /path/to/models explicitly."
        )

    @cached_property
    def packages(self) -> dict[str, KI]:
        out: dict[str, KI] = {}
        roots = [self.models_dir] + ([self.user_dir] if self.user_dir and self.user_dir.is_dir() else [])
        for root in roots:
            for d in sorted(root.iterdir()):
                if d.is_dir() and (d / "SKILL.md").exists() and d.name not in out:
                    out[d.name] = KI(name=d.name, root=d)
        return out

    def refresh(self) -> None:
        """Drop the cached package map after an import."""
        self.__dict__.pop("packages", None)

    def get(self, name: str) -> KI:
        """Look up a KI, tolerating case and separator differences."""
        if name in self.packages:
            return self.packages[name]
        norm = _norm(name)
        for k, v in self.packages.items():
            if _norm(k) == norm:
                return v
        matches = [k for k in self.packages if norm in _norm(k)]
        if len(matches) == 1:
            return self.packages[matches[0]]
        if matches:
            raise KeyError(f"{name!r} is ambiguous: {', '.join(sorted(matches))}")
        raise KeyError(f"no KI named {name!r} (have {len(self.packages)})")

    def search(self, term: str) -> list[KI]:
        t = term.lower()
        hits = []
        for ki in self.packages.values():
            hay = f"{ki.name} {ki.meta.get('reference') or ''} {ki.meta.get('language') or ''}".lower()
            if t in hay:
                hits.append(ki)
        return hits

    def __len__(self) -> int:
        return len(self.packages)

    def __iter__(self):
        return iter(self.packages.values())


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("+", "plus"))
