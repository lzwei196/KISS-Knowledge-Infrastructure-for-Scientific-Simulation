"""flow.resolve — which KIs does this task involve? Never guess.

Plan v3 map A2. Learns from chat's `_known_model_ids` / `_detect_models_in_text`
(cli_process_manager.py L2128-2154) and fixes its bug at L2149: the dead
`tok.replace(r"\\_", ...)` meant `CaMa_Flood` only matched the underscore spelling,
so "VIC–CaMa" and "run VIC and CaMa-Flood" detected VIC alone. Here both the
catalogue id and the text are normalised the same way the harness's ki_path.py
does (L28-29): `[-_/+ ]+` -> one space, lower case.

It also drops chat's "1-2 hits else nothing" rule (L2153): every hit is
returned; a token that matches more than one id is reported as ambiguous.

The catalogue is data, not guesswork: on the server the `models` table
(id, name, ki_path); on the desktop the bundled manifest list. Coupled partners
come from the shipped coupling configs (derive_plan.py build_indexes step 4,
L132-146): `coupling_config_<S>_to_<T>.yaml`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SPLIT = re.compile(r"[\W_]+", re.UNICODE)  # punctuation in every UI language
# Candidate model names are ASCII identifiers even when the surrounding request is
# written in Chinese (``我想用CRHM模拟融雪径流``).  Splitting only on whitespace made
# that entire sentence look like one mixed-case "unknown model" after CRHM had already
# been resolved.  Extract the identifier runs instead; separators inside real model
# names remain available to the VIC-CaMa / WRF_Hydro logic below.
_CJK_GLUE = re.compile(r"(?<=[A-Za-z0-9])(?=[\u3400-\u9fff\uf900-\ufaff])|"
                       r"(?<=[\u3400-\u9fff\uf900-\ufaff])(?=[A-Za-z0-9])")

_ASCII_MODEL_TOKEN = re.compile(
    r"[A-Za-z][A-Za-z0-9]*(?:[-–—_/+][A-Za-z][A-Za-z0-9]*)*\+?"
)

# Common words that must never be treated as a model-name prefix.
_STOP = {"run", "runs", "model", "models", "flood", "floods", "water", "river", "basin", "with",
         "and", "the", "for", "from", "into", "data", "crop", "yield", "soil", "snow", "lake",
         "test", "case", "plan", "coupled", "couple", "coupling", "simulate", "simulation",
         "route", "routing", "ocean", "wave", "global", "china", "daily", "hourly"}


def norm(s: str) -> str:
    """Same normalisation as ki_tools_common.harness.ki_path._norm, plus a split between
    latin/digit runs and CJK runs (kimi block-C review: "VIC-CaMa耦合" must tokenize as
    "vic cama 耦合", not glue the model name to the Chinese verb)."""
    return _SPLIT.sub(" ", _CJK_GLUE.sub(" ", str(s or ""))).strip().lower()


@dataclass
class CatalogueEntry:
    id: str
    name: str = ""
    ki_path: str | None = None

    def keys(self) -> set[str]:
        return {norm(self.id), norm(self.name)} - {""}


@dataclass
class Resolution:
    resolved: list[str] = field(default_factory=list)       # catalogue ids, in text order
    ambiguous: dict[str, list[str]] = field(default_factory=dict)  # token -> candidate ids
    unknown: list[str] = field(default_factory=list)        # model-like tokens with no match
    partners_missing: list[str] = field(default_factory=list)  # coupled partners of a resolved
                                                               # model that are NOT in the run
                                                               # (to ASK about; never auto-added)

    @property
    def ok(self) -> bool:
        """Safe to plan without a question: something resolved, nothing ambiguous or unknown."""
        return bool(self.resolved) and not self.ambiguous and not self.unknown


_SCIENCE_HINTS = (
    "simulat", "model", "run ", "forecast", "calibrat", "flood", "yield", "discharge",
    "runoff", "routing", "projection", "scenario", "couple", "模拟", "运行", "耦合", "率定",
    "洪水", "径流", "产量", "预报", "准备", "输入数据", "数据清单", "规划",
    "prepare", "input data", "data inventory", "plan ", "planning",
)
_PURE_CHAT = ("hello", "hi", "thanks", "thank you", "what can you do", "who are you",
              "你好", "谢谢", "你能做什么")


def is_scientific_task(text: str) -> bool:
    """Cheap gate (learned from plan_extractor._looks_like_pure_chat): greetings and
    'what can you do' are not scientific tasks; anything naming a simulation is."""
    t = (text or "").strip().lower()
    if not t:
        return False
    if len(t) < 60 and any(p in t for p in _PURE_CHAT):
        return False
    return any(h in t for h in _SCIENCE_HINTS)


def _catalogue_index(catalogue) -> dict[str, list[str]]:
    """normalised key -> [ids]. Accepts CatalogueEntry objects, dicts or plain ids."""
    idx: dict[str, list[str]] = {}
    for e in catalogue:
        if isinstance(e, CatalogueEntry):
            ent = e
        elif isinstance(e, dict):
            ent = CatalogueEntry(id=str(e.get("id") or e.get("name") or ""),
                                 name=str(e.get("name") or ""), ki_path=e.get("ki_path"))
        else:
            ent = CatalogueEntry(id=str(e))
        if not ent.id:
            continue
        for k in ent.keys():
            idx.setdefault(k, [])
            if ent.id not in idx[k]:
                idx[k].append(ent.id)
    return idx


def _find_in_text(text: str, idx: dict[str, list[str]]) -> list[tuple[int, str, list[str]]]:
    """Return (position, key, ids) for every catalogue key found in the normalised text.
    Longest keys first so 'cama flood' wins over 'cama' when both are catalogue entries."""
    t = " " + norm(text) + " "
    hits: list[tuple[int, str, list[str]]] = []
    taken: list[tuple[int, int]] = []
    for key in sorted(idx, key=len, reverse=True):
        if len(key) < 2:
            continue
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", t):
            span = (m.start(), m.end())
            if any(a <= span[0] < b or a < span[1] <= b for a, b in taken):
                continue  # inside a longer match already claimed
            taken.append(span)
            hits.append((span[0], key, idx[key]))
    hits.sort()
    return hits


def resolve_kis(text: str, selected: list[str] | None, catalogue,
                couplings: list[tuple[str, str]] | None = None) -> Resolution:
    """Resolve the KIs a task involves from the ticked selection AND the task text.

    selected  : ids the user already picked (desktop tick boxes / chat entry). Kept first.
    catalogue : iterable of CatalogueEntry | dict(id,name,ki_path) | id strings.
    couplings : optional list of (source_id, target_id) pairs from the coupling configs;
                when a resolved model has a coupled partner named NOWHERE, it is NOT added
                silently — it is reported in `partners_added` only when the text names the
                pair form ("VIC-CaMa"), i.e. both ends were named; otherwise the missing
                partner is a planning question, not a resolution.
    """
    idx = _catalogue_index(catalogue)
    res = Resolution()
    for s in (selected or []):
        sid = str(s)
        if sid and sid not in res.resolved:
            res.resolved.append(sid)
    for _, key, ids in _find_in_text(text, idx):
        if len(ids) == 1:
            if ids[0] not in res.resolved:
                res.resolved.append(ids[0])
        else:
            # one normalised key maps to several ids (e.g. two catalogue rows share a name)
            already = [i for i in ids if i in res.resolved]
            if already:
                continue
            res.ambiguous[key] = list(ids)
    # Short forms ("VIC–CaMa" → CaMa_Flood): a leftover token of ≥4 chars that is the prefix of
    # the FIRST word of exactly one catalogue key resolves to it; of several → ambiguous.
    # Never for common words (_STOP), never guessed beyond a single candidate.
    matched_spans = {key for _, key, _ in _find_in_text(text, idx)}
    covered = " ".join(matched_spans)
    first_words: dict[str, list[str]] = {}
    for key, ids in idx.items():
        fw = key.split(" ", 1)[0]
        for i in ids:
            first_words.setdefault(fw, [])
            if i not in first_words[fw]:
                first_words[fw].append(i)
    for tok in norm(text).split(" "):
        if len(tok) < 4 or tok in _STOP or tok in covered.split(" ") or not tok.isalnum():
            continue
        if tok in idx:
            continue  # exact keys were handled above
        cands: list[str] = []
        for fw, ids in first_words.items():
            if fw.startswith(tok):      # 'cama' == first word of 'cama flood' counts too
                for i in ids:
                    if i not in cands:
                        cands.append(i)
        cands = [c for c in cands if c not in res.resolved]
        if len(cands) == 1:
            res.resolved.append(cands[0])
        elif len(cands) > 1:
            res.ambiguous[tok] = cands
    # Unknown model-like names (codex #3): a token the user wrote like a model name — it has a
    # capital letter after the first, is ALL CAPS, mixes digits and letters, or is dash-joined
    # to a resolved model ("VIC-CaMa") — that matched nothing must be REPORTED, never dropped.
    matched_words = set()
    for key in list(matched_spans) + [norm(i) for i in res.resolved] + list(res.ambiguous):
        matched_words.update(key.split(" "))
    resolved_norm = {norm(i) for i in res.resolved}
    raw_tokens = _ASCII_MODEL_TOKEN.findall(text or "")
    for raw in raw_tokens:
        parts = [p for p in re.split(r"[-–—_/+]", raw) if p]
        joined_to_model = any(norm(p) in resolved_norm for p in parts) and len(parts) > 1
        for p in parts:
            n = norm(p)
            if not n or len(n) < 3 or n in _STOP or n in matched_words or not n.isalnum():
                continue
            model_like = (p[1:] != p[1:].lower()) or (p.isupper() and len(p) >= 3) or \
                         (any(ch.isdigit() for ch in p) and any(ch.isalpha() for ch in p)) or \
                         joined_to_model
            if model_like and p not in res.unknown:
                res.unknown.append(p)
    # Coupled partners of a resolved model that are not in the run: reported for the
    # planning turn to ASK about ("you named VIC; CaMa_Flood is its routing partner —
    # include it?"). Never auto-added.
    if couplings:
        have = set(res.resolved)
        for src, tgt in couplings:
            for a, b in ((src, tgt), (tgt, src)):
                if a in have and b not in have and b not in res.partners_missing:
                    res.partners_missing.append(b)
    return res


def coupling_pairs(couplings_dir: Path | str) -> list[tuple[str, str]]:
    """Every (source, target) pair the shipped coupling configs know about."""
    d = Path(couplings_dir)
    out: list[tuple[str, str]] = []
    if not d.is_dir():
        return out
    for yml in sorted(d.glob("coupling_config_*.yaml")):
        stem = yml.stem.replace("coupling_config_", "")
        if "_to_" in stem:
            src, tgt = stem.split("_to_", 1)
            out.append((src, tgt))
    return out


def couplings_for(ids: list[str], couplings_dir: Path | str, one_end: bool = False) -> list[dict]:
    """Edges from `coupling_config_<S>_to_<T>.yaml` files (derive_plan L132-146).
    Default: both ends in `ids`. one_end=True: edges touching ANY id (the other end may be
    missing from the run — codex #3) with `partner_missing` set."""
    d = Path(couplings_dir)
    out: list[dict] = []
    if not d.is_dir():
        return out
    want = set(ids)
    for yml in sorted(d.glob("coupling_config_*.yaml")):
        stem = yml.stem.replace("coupling_config_", "")
        if "_to_" not in stem:
            continue
        src, tgt = stem.split("_to_", 1)
        both = src in want and tgt in want
        touch = src in want or tgt in want
        if both or (one_end and touch):
            py = d / f"couple_{src}_to_{tgt}.py"
            edge = {"source": src, "target": tgt, "edge_id": f"{src}_to_{tgt}",
                    "config_path": str(yml), "wrapper_path": str(py) if py.exists() else None,
                    "variables": [], "partner_missing": (None if both else (tgt if src in want else src))}
            try:
                import yaml as _y
                cfg = _y.safe_load(yml.read_text(errors="ignore")) or {}
                edge["variables"] = [e.get("canonical_id") for e in (cfg.get("forward_edges") or [])
                                     if isinstance(e, dict) and e.get("canonical_id")]
                edge["edge_type"] = ((cfg.get("metadata") or {}).get("edge_type"))
            except Exception:
                pass
            out.append(edge)
    return out


def partners_named_but_unselected(res: Resolution, couplings: list[dict]) -> list[str]:
    """Ids that appear as the other end of an edge whose one end is resolved — for the
    planning turn to ASK about ('you named VIC; CaMa_Flood is its routing partner —
    include it?'). Never auto-added. Same as Resolution.partners_missing when
    resolve_kis() was given the coupling pairs."""
    have = set(res.resolved)
    out: list[str] = []
    for e in couplings:
        for a, b in ((e["source"], e["target"]), (e["target"], e["source"])):
            if a in have and b not in have and b not in out:
                out.append(b)
    return out
