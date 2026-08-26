"""The literature behind a model: what to read, and how to get it.

Every KI ships ``docs/papers.json`` — the papers that document the model it
wraps, as metadata. Not the PDFs. Roughly half of them are subscription
articles that reached this machine through an institutional login, and
redistributing those would be republishing someone else's copyrighted work.
DOIs travel freely; the articles stay where their publishers put them.

That split is the useful part, not a limitation to apologise for. An agent
reading ``papers.json`` knows which papers exist, what each one is *for*
(``role``) and which quantities it covers (``serves``), so it can tell the user
exactly which three PDFs to fetch for the job in front of them rather than
"go and read the literature".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: Statuses that mean anyone can download the paper for free. ``oa_manual`` is
#: deliberately absent: those arrived through a person's own subscription, so
#: calling them open would send users to a paywall labelled "free".
OPEN = {"oa_gold", "oa_green", "oa_diamond"}

FILENAME = "papers.json"

SCHEMA_NOTE = (
    "Metadata only — no PDFs are redistributed. Papers marked "
    "access=subscription need your own institutional or personal access; "
    "access=open can be downloaded by anyone from the DOI link."
)


@dataclass
class Paper:
    doi: str
    title: str
    role: str = ""
    serves: tuple[str, ...] = ()
    access: str = "unknown"

    @property
    def url(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else ""

    @property
    def open_access(self) -> bool:
        return self.access == "open"

    @classmethod
    def from_gathered(cls, row: dict) -> "Paper | None":
        """Convert one KDT ``gathered_papers.json`` row into a shippable record.

        ``text_path`` is dropped on purpose: it points into this machine's
        paper_cache and names extracted full text, which is the one field that
        must not travel.
        """
        doi = (row.get("doi") or "").strip()
        title = (row.get("title") or "").strip()
        if not doi and not title:
            return None
        return cls(
            doi=doi,
            title=title,
            role=(row.get("role") or "").strip(),
            serves=tuple(row.get("serves") or ()),
            access="open" if row.get("status") in OPEN else "subscription",
        )

    def as_dict(self) -> dict:
        d = {"doi": self.doi, "title": self.title, "access": self.access}
        if self.role:
            d["role"] = self.role
        if self.serves:
            d["serves"] = list(self.serves)
        return d


@dataclass
class Library:
    model: str
    papers: list[Paper]

    @property
    def open_papers(self) -> list[Paper]:
        return [p for p in self.papers if p.open_access]

    @property
    def gated(self) -> list[Paper]:
        return [p for p in self.papers if not p.open_access]

    def for_quantity(self, q: str) -> list[Paper]:
        """Papers covering one quantity — what the agent asks when it is about
        to model discharge and wants the two papers that actually discuss it."""
        ql = q.lower()
        return [p for p in self.papers if any(ql == s.lower() for s in p.serves)]

    def by_role(self, role: str) -> list[Paper]:
        return [p for p in self.papers if p.role.lower() == role.lower()]

    @property
    def roles(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in self.papers:
            if p.role:
                out[p.role] = out.get(p.role, 0) + 1
        return out

    def as_dict(self) -> dict:
        return {"model": self.model, "note": SCHEMA_NOTE,
                "count": len(self.papers),
                "open_access": len(self.open_papers),
                "papers": [p.as_dict() for p in self.papers]}

    def dumps(self) -> str:
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False) + "\n"


def path_for(ki) -> Path:
    return Path(ki.root) / "docs" / FILENAME


def load(ki) -> Library | None:
    """The KI's shipped library, or None if it ships none."""
    p = path_for(ki)
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = doc.get("papers") if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        return None
    papers = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        papers.append(Paper(doi=(r.get("doi") or "").strip(),
                            title=(r.get("title") or "").strip(),
                            role=(r.get("role") or "").strip(),
                            serves=tuple(r.get("serves") or ()),
                            access=r.get("access") or "unknown"))
    name = doc.get("model") if isinstance(doc, dict) else None
    return Library(model=name or getattr(ki, "name", "?"), papers=papers)


# ---------------------------------------------------------------- checking

@dataclass
class Report:
    model: str
    ok: bool
    count: int = 0
    open_access: int = 0
    problems: list[str] = None

    def line(self) -> str:
        if not self.ok:
            return f"{self.model}: {'; '.join(self.problems or ['no papers.json'])}"
        gated = self.count - self.open_access
        tail = f", {gated} need your own access" if gated else ""
        return f"{self.model}: {self.count} papers, {self.open_access} downloadable{tail}"


def check(ki) -> Report:
    """Is this KI's shipped literature usable, and does it leak anything?"""
    lib = load(ki)
    if lib is None:
        return Report(ki.name, False, problems=[f"no docs/{FILENAME}"])
    problems: list[str] = []
    if not lib.papers:
        problems.append("papers.json is empty")
    no_doi = [p for p in lib.papers if not p.doi]
    if no_doi:
        problems.append(f"{len(no_doi)} papers have no DOI, so they cannot be fetched")
    # A shipped record must not carry local paths or extracted full text.
    raw = path_for(ki).read_text(encoding="utf-8", errors="replace")
    for leak in ("text_path", "paper_cache", "/home/", "/mnt/"):
        if leak in raw:
            problems.append(f"leaks {leak} — regenerate this file")
            break
    return Report(ki.name, not problems, len(lib.papers),
                  len(lib.open_papers), problems or None)
