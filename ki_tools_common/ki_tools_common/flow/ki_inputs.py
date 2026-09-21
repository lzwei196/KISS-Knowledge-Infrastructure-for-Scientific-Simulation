"""ki_inputs — a model's inputs read from its OWN KI (dag.yaml + SKILL.md), not from the ATA card.

Owner (2026-09-16): the planner must read the SKILL and the dag directly. The dag is the model's flow and how
its variables connect (the root); the SKILL is the general flow — the KI's stages and their tools. The ATA
card is an a2a artifact generated from format_spec (a projection of the dag) and was months stale.

Owner (2026-09-18): NO mapping of inputs to stages. The planner used to guess which stage "prepares" an
input by matching words (rain/dem/soil…) between the input and the stage — that guessing decided ask-vs-default
and broke ("rain" inside "drainage"). Now: the dag's own `source_kind` decides (only `user_provided` is shown as
a question), and the SKILL stages are listed as they are for the agent to read. If the dag is wrong (an input
marked user_provided that a stage computes), the fix is the dag, not a planner heuristic.

What this module returns for one model (pure, never raises):
  inputs: [{ id, name, unit, category, dag_category, source_kind, notes, canonical_id, modes? }]
    id = canonical_id when the vocabulary resolves the dag name, else a slug of the dag name
  skill_stages(ki_root): [{code, name, tools, text}] — the SKILL's pipeline stages, verbatim, no families
Canonical ids come from ata-kdt/artifacts/canonical_variable_registry.yaml + the alias table the card
generator uses (the ONE vocabulary) — nothing new is kept here.
"""
from __future__ import annotations

import re
from pathlib import Path

DAG_SECTIONS = ("forcing", "parameters", "initial_conditions", "boundary_conditions", "optional", "static")
# dag source_kind values the KI resolves by itself (no user answer needed)
KI_RESOLVED_SOURCE_KINDS = {"calibrated", "default", "dataset_lookup", "derived", "computed", "internal"}


def _yaml():
    import yaml
    return yaml


def _slug(name: str) -> str:
    s = re.sub(r"\(.*?\)", " ", str(name or ""))
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s or "unnamed"


# ─── the ONE vocabulary (ata-kdt registry + the card generator's alias table) ───────────────────────
_ALIAS_CACHE: dict[str, dict[str, str]] = {}


_FACTS_CACHE: dict[str, dict[str, dict]] = {}
# registry match confidences that count as an alias; 'substring' entries are how the junk got in
_EXACT_CONFIDENCES = {"exact_alias", "skill_md_exact_alias", "domain_disambiguated"}
# table aliases that name a model OUTPUT only; the same word as an INPUT means something else
_OUTPUT_ONLY_ALIASES = {"zsmax", "hmax", "point_zs", "snow", "evap", "sm", "ea", "ae", "inundation"}
# bare words that mean the ATMOSPHERIC quantity only when they are a forcing input
_FORCING_ONLY_HEADS = {"temperature", "temp", "evaporation", "pressure", "humidity", "wind"}
# output-side heads that name DIFFERENT quantities in different models (H = river depth / ice thickness /
# wave height; temperature = sea / lake / ice / air; stage = water level / crop stage): never resolved
# from a global table — the per-model canonical_id in the dag is the KDT fix
_AMBIGUOUS_OUTPUT_HEADS = {"temperature", "temp", "surface_temp", "t", "h", "s", "q", "u", "v", "m", "e",
                           "p", "z", "stage", "level", "depth"}


def _card_gen_module(root: Path):
    """The card generator's tables (EXTRA_ALIASES, EXTRA_TARGET_DIMENSIONS) — imported by path so there is one table."""
    import importlib.util, sys
    p = Path(root) / "ata-kdt" / "pipelines" / "ata_pipeline1_card_gen.py"
    if not p.is_file():
        return None
    mod = sys.modules.get("_ata_card_gen")
    if mod is not None and getattr(mod, "__file__", None) == str(p):
        return mod
    spec = importlib.util.spec_from_file_location("_ata_card_gen", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ata_card_gen"] = mod
    spec.loader.exec_module(mod)
    return mod


def canonical_facts(root: Path) -> dict[str, dict]:
    """{canonical_id: {dims: [vectors], preferred_unit, types: set()}}. S0 round 2 (2026-09-21): the guard is
    the registry's own `dimension` field per id (plus EXTRA_TARGET_DIMENSIONS for alias targets outside the
    registry) — NOT the registry's unit lists, which were built by name matching and carry junk (MONICA's
    crop "Stage", unit "0-7", under water_surface_elevation)."""
    key = str(root)
    if key in _FACTS_CACHE:
        return _FACTS_CACHE[key]
    facts: dict[str, dict] = {}
    try:
        reg = _yaml().safe_load((Path(root) / "ata-kdt" / "artifacts" / "canonical_variable_registry.yaml")
                                .read_text(encoding="utf-8")) or {}
        for cid, info in (reg.get("registry") or {}).items():
            tt = info.get("target_type")
            try:
                import ast
                tt = tt if isinstance(tt, list) else (ast.literal_eval(tt) if isinstance(tt, str) and tt.startswith("[") else [tt])
            except Exception:
                tt = ["variable"]
            facts[cid] = {"dims": _dims_from_text(info.get("dimension")),
                          "preferred_unit": info.get("preferred_unit"),
                          "types": {str(t) for t in (tt or ["variable"])}}
    except Exception:
        pass
    try:
        mod = _card_gen_module(root)
        for cid, dim in (getattr(mod, "EXTRA_TARGET_DIMENSIONS", {}) or {}).items():
            facts.setdefault(cid, {"dims": _dims_from_text(dim), "preferred_unit": None, "types": {"variable"}})
    except Exception:
        pass
    _FACTS_CACHE[key] = facts
    return facts


_SUPERSCRIPTS = str.maketrans({"²": "2", "³": "3", "⁻": "-", "¹": "1", "⁰": "0", "μ": "u", "µ": "u", "°": "deg",
                                "δ": "d", "Δ": "d"})

# ── S0 round 2 (2026-09-21, codex + kimi): the unit guard is DIMENSIONAL. A dag unit string is parsed into
# base dimensions (L length, M mass, T time, Theta temperature; "1" = dimensionless) and compared with the
# canonical id's declared `dimension` (the registry field, e.g. "L^3 T^-1"; alias-table targets outside the
# registry carry theirs in EXTRA_TARGET_DIMENSIONS). "m3/m3" is not a discharge, "kg/s" is not a yield,
# "W/m2" is not a runoff, "m/s" is not m3/s — whatever junk the registry's unit lists carry.
_DIM_TOKENS = {
    # length
    "m": "L", "mm": "L", "cm": "L", "km": "L", "um": "L", "in": "L", "inch": "L", "inches": "L", "ft": "L", "feet": "L",
    "mi": "L", "mile": "L", "mwe": "L", "m_we": "L", "masl": "L", "m_asl": "L",
    # area / volume
    "m2": "L2", "cm2": "L2", "km2": "L2", "ha": "L2", "hectare": "L2", "acre": "L2", "ac": "L2", "ft2": "L2",
    "m3": "L3", "cm3": "L3", "km3": "L3", "hm3": "L3", "l": "L3", "liter": "L3", "litre": "L3", "ml": "L3", "ft3": "L3",
    "gal": "L3", "gallon": "L3", "cms": "L3T-1", "cfs": "L3T-1",
    # time
    "s": "T", "sec": "T", "second": "T", "seconds": "T", "min": "T", "minute": "T", "h": "T", "hr": "T", "hour": "T",
    "hours": "T", "d": "T", "day": "T", "days": "T", "wk": "T", "week": "T", "mo": "T", "month": "T", "months": "T",
    "yr": "T", "year": "T", "years": "T", "a": "T", "timestep": "T", "step": "T", "dt": "T", "interval": "T",
    "forcingstep": "T", "season": "T",
    # mass (a mole of carbon / nitrogen counts as a mass for flux purposes)
    "kg": "M", "g": "M", "mg": "M", "ug": "M", "t": "M", "tonne": "M", "tonnes": "M", "ton": "M", "tons": "M",
    "lb": "M", "gc": "M", "kgc": "M", "mgc": "M", "kgn": "M", "gn": "M", "kgp": "M", "kgco2": "M", "gco2": "M",
    "kgdm": "M", "gdm": "M", "mol": "M", "mmol": "M", "umol": "M", "kmol": "M", "bushel": "M", "bushels": "M", "bu": "M",
    # temperature
    "degc": "Theta", "k": "Theta", "degk": "Theta", "kelvin": "Theta", "degf": "Theta", "f": "Theta", "celsius": "Theta",
    # pressure  M L^-1 T^-2
    "pa": "ML-1T-2", "hpa": "ML-1T-2", "kpa": "ML-1T-2", "mpa": "ML-1T-2", "mb": "ML-1T-2", "mbar": "ML-1T-2",
    "bar": "ML-1T-2", "atm": "ML-1T-2", "psi": "ML-1T-2", "uatm": "ML-1T-2",
    # power / energy
    "w": "ML2T-3", "kw": "ML2T-3", "mw": "ML2T-3", "gw": "ML2T-3", "j": "ML2T-2", "kj": "ML2T-2", "mj": "ML2T-2",
    "gj": "ML2T-2", "cal": "ML2T-2", "kcal": "ML2T-2", "langley": "MT-2", "ly": "MT-2", "wh": "ML2T-2", "kwh": "ML2T-2",
    "mwh": "ML2T-2",
    # dimensionless
    "-": "1", "1": "1", "fraction": "1", "frac": "1", "%": "1", "percent": "1", "pct": "1", "tenths": "1", "oktas": "1",
    "dimensionless": "1", "unitless": "1", "ratio": "1", "psu": "1", "ppt": "1", "ppm": "1", "ppmv": "1", "ppb": "1",
    "pss": "1", "pu": "1",
}
_DIM_VEC = {"L": (1, 0, 0, 0), "L2": (2, 0, 0, 0), "L3": (3, 0, 0, 0), "L3T-1": (3, 0, -1, 0), "T": (0, 0, 1, 0),
            "M": (0, 1, 0, 0), "Theta": (0, 0, 0, 1), "ML-1T-2": (-1, 1, -2, 0), "ML2T-3": (2, 1, -3, 0),
            "ML2T-2": (2, 1, -2, 0), "MT-2": (0, 1, -2, 0), "1": (0, 0, 0, 0)}
# units that say "this is not a physical quantity" (a switch, a code, a bundle of things): a canonical id
# with a dimension can never fit them — a real quantity has a real unit
_NONPHYSICAL_UNITS = {"n/a", "na", "none", "mixed", "categorical", "switch", "enum", "boolean", "bool", "code",
                      "count", "date", "varies", "various", "flag", "logical", "integer", "selector", "text",
                      "string", "yrdoy", "id", "index", "list", "path", "file", "0/1", "true/false", "on/off",
                      "level index", "grid index", "cell index", "layer index", "node index"}   # Veros kbot: an index, not a height
# words that only annotate a unit ("kg C/ha", "mm H2O", "m SWE", "umol CO2/m2/s"): read past them
_INERT_UNIT_WORDS = {"c", "n", "p", "h2o", "swe", "we", "co2", "o2", "dm", "water", "ice", "snow", "liquid",
                     "equivalent", "eq", "cms", "si", "us"}


def _unit_first_alternative(unit: str) -> str:
    """'ft (US) / m (SI)' → 'ft'; 'kg/(m2*s)' keeps its denominator; 'mm/s (kg/m2/s)' → 'mm/s';
    'kg / ha / yr (note)' → 'kg / ha / yr' (a spaced slash is DIVISION unless it separates annotated
    alternatives)."""
    raw = str(unit or "").strip().lower().translate(_SUPERSCRIPTS)
    raw = re.sub(r"([/*])\s+\(", r"\1(", raw)                        # "kg/ (m2*s)" → "kg/(m2*s)"
    annotated_alternatives = bool(re.search(r"\)\s*/\s*", raw))   # "ft (US) / m (SI)": alternatives, not a division
    u = re.sub(r"(?<![/*])\s*\([^()]*\)", " ", raw)         # drop annotations; keep parentheses after / or *
    u = u.split(",")[0]
    u = re.split(r"\s+or\s+|;|\s\|\s", u)[0]
    if "\u0020/\u0020" in u:
        parts = [x.strip() for x in u.split(" / ")]
        # "kg / ha / yr", "kg C / ha" are divisions (each part = one known unit token, maybe with an inert
        # word, and the parts are different dimensions); "m3/s / cfs", "ft (US) / m (SI)", "% / kPa / mbar"
        # (a parallel list for rh / vpd / press), "m / degrees / D8 code / count" are alternatives — first
        dims = [_dimension(x) for x in parts]
        single = [re.fullmatch(r"[a-z%µ]+\d*(\s+[a-z0-9]+)?", x) is not None for x in parts]   # one unit token (+ inert word)
        if annotated_alternatives or any(d is None for d in dims) or len(set(dims)) != len(dims) \
                or any(d == (0, 0, 0, 0) for d in dims) or any("/" in x for x in parts) or not all(single) \
                or any(_dimension(x) != _dimension(x.split()[0]) for x in parts):
            u = parts[0]                                   # "Pa / kg m-3" (two quantities) → Pa; "kg / ha / yr" stays a division
    u = re.sub(r"^(deg\s*c|degc|celsius)\s*/\s*(deg\s*f|degf|f)$", r"\1", u.strip())   # "deg C/F" = either scale
    return re.sub(r"\s+", " ", u).strip()


_DRY_MATTER_IDS = {"biomass", "grain_yield"}


def _is_carbon_unit(unit: str) -> bool:
    """'gC/m2', 'kg C/ha', 'g C m-2', 'kgC ha-1': a mass of CARBON."""
    u = _unit_first_alternative(unit)
    return bool(re.search(r"\b(?:g|kg|mg|t|tonne)\s*c\b|\b(?:g|kg|mg|t)c\b|carbon", u))


def unit_is_nonphysical(unit: str) -> bool:
    return _unit_first_alternative(unit) in _NONPHYSICAL_UNITS


def _dimension(unit: str) -> tuple[int, int, int, int] | None:
    """Base-dimension vector (L, M, T, Theta) of a unit string, or None when it cannot be read.
    Tokens after the first recognised unit that are not units are read as annotation ("K above
    freezing" → Theta); a string whose FIRST token is unknown is unreadable."""
    raw = re.sub(r"\s*\(.*$", "", str(unit or "").strip())
    if re.match(r"^[A-Z]\s*(\||in\s*\[|,)", raw):
        return None                                        # "T | H | M" (a mode switch), "T in [-3,45] degC" (a variable list)
    m_abs = re.fullmatch(r"([LMT](?:\^?-?\d)?)((?:\s*/\s*[LMT](?:\^?-?\d)?)+)", raw)   # HYDRUS "L/T", "M/L^3": abstract dimensions
    if m_abs:                                              # (whole string, exponents kept; "T | H | M" is not this)
        vec = [0, 0, 0, 0]; sign = 1
        for tok in re.findall(r"([LMT])\^?(-?\d)?|(/)", raw):
            if tok[2] == "/": sign = -1; continue
            vec[{"L": 0, "M": 1, "T": 2}[tok[0]]] += sign * int(tok[1] or 1)
        return tuple(vec)
    u = _unit_first_alternative(unit)
    if not u or u in _NONPHYSICAL_UNITS:
        return None
    if re.fullmatch(r"[\d.\-–/ ]+", u):
        return (0, 0, 0, 0)                            # "0-7", "0/1", "0-1": a code or a ratio, dimensionless
    u = u.replace("^", "").replace("**", "").replace("·", " ")
    u = re.sub(r"/\s*\(([^()]*)\)", lambda m: "/" + re.sub(r"[\s*]+", "/", m.group(1).strip()), u)   # kg/(m2*s) → kg/m2/s
    u = u.replace("*", " ")
    u = re.sub(r"\b(deg|degree|degrees)[\s_]*c\b", "degc", u); u = re.sub(r"\b(deg|degree|degrees)[\s_]*k\b", "degk", u)
    u = re.sub(r"\b(deg|degree|degrees)[\s_]*f\b", "degf", u); u = re.sub(r"\bdgc\b", "degc", u)
    u = re.sub(r"\bm\s*w\.?e\.?\b", "mwe", u); u = re.sub(r"\bm\s*asl\b", "masl", u)
    u = u.replace(" per ", "/").replace("(", " ").replace(")", " ").replace(".", "")
    u = re.sub(r"\s*/\s*", "/", u)
    vec = [0, 0, 0, 0]; sign = 1; seen = False
    for tok in re.split(r"(/|\s+)", u):
        if not tok or tok.isspace():
            sign = 1; continue                         # "mmol/m3 cm/s": a space starts a new product term
        if tok == "/":
            sign = -1; continue
        if tok in _INERT_UNIT_WORDS and seen:
            continue                                   # "umol CO2/m2/s": CO2 annotates the mole
        m = re.fullmatch(r"([a-z%µ]+)(-?\d+)?", tok)
        if not m:
            if seen:
                break                                  # "m/s at 10 m": the unit is complete, the rest is a note
            return None
        name, exp_s = m.group(1), m.group(2)
        exp = int(exp_s) if exp_s else 1
        if name in _DIM_TOKENS and not (exp_s and not exp_s.startswith("-") and name + exp_s in _DIM_TOKENS):
            base = _DIM_TOKENS[name]
        elif exp_s and not exp_s.startswith("-") and name + exp_s in _DIM_TOKENS:
            base = _DIM_TOKENS[name + exp_s]; exp = 1   # "m2", "m3" as one token
        elif name in _INERT_UNIT_WORDS and seen:
            continue                                   # "kg C/ha": C annotates the mass
        elif name == "c" and not seen:
            base = "Theta"                             # a bare "C" is Celsius
        elif seen:
            break                                      # "K above freezing": a note after the unit
        else:
            return None
        v = _DIM_VEC[base]; seen = True
        for i in range(4):
            vec[i] += sign * exp * v[i]
    return tuple(vec) if seen else None


def _dims_from_text(text: str | None) -> list[tuple[int, int, int, int]]:
    """Registry grammar → vectors: 'L T^-1' → (1,0,-1,0); 'L or 1' → both; 'M L^-2 T^-1' → (-2,1,-1,0)."""
    out = []
    for alt in re.split(r"\s+or\s+", str(text or "").strip()):
        alt = alt.strip()
        if not alt:
            continue
        if alt in ("1", "dimensionless"):
            out.append((0, 0, 0, 0)); continue
        vec = [0, 0, 0, 0]; ok = True
        for tok in alt.split():
            m = re.fullmatch(r"(L|M|T|Theta)(?:\^(-?\d+))?", tok)
            if not m:
                ok = False; break
            i = {"L": 0, "M": 1, "T": 2, "Theta": 3}[m.group(1)]
            vec[i] += int(m.group(2) or 1)
        if ok:
            out.append(tuple(vec))
    return out


def _unit_key(u: str) -> str:
    """Kept for callers/tests: one spelling per unit ('m³ s⁻¹', 'm3 s-1', 'm^3/s' → 'm3/s')."""
    d = _dimension(u)
    canon = {(3, 0, -1, 0): "m3/s", (1, 0, -1, 0): "mm/day", (0, 0, 0, 1): "degc", (1, 0, 0, 0): "mm",
             (-2, 1, -1, 0): "gc/m2/day", (-2, 1, 0, 0): "kg/ha", (0, 1, -3, 0): "w/m2", (0, 0, 0, 0): "-"}
    return canon.get(d, _unit_first_alternative(u).replace(" ", ""))


def unit_fits(unit: str, cid: str, facts: dict[str, dict]) -> bool:
    """True when the dag unit's DIMENSION is one the canonical id declares. Unknown/unreadable units and
    ids without a declared dimension pass (cannot be judged — the name decides). Two water conventions
    are accepted: a depth without its period ("mm" = mm per step) fits a depth RATE, and a mass per area of
    water (kg/m2 = mm) fits a water depth or depth rate. A volume (m3) never fits a volume rate (m3/s)."""
    dims = (facts.get(cid) or {}).get("dims") or []
    if dims and unit_is_nonphysical(unit):
        return False                                     # a switch / code / bundle is not a physical quantity
    if cid in _DRY_MATTER_IDS and _is_carbon_unit(unit):
        return False                                     # gC/m2 is a carbon stock, not dry biomass / yield (DayCent aglivc)
    d = _dimension(unit)
    if d is None or not dims:
        return True
    if d in dims:
        return True
    L, M, T, Th = d
    pref = str((facts.get(cid) or {}).get("preferred_unit") or "").lower()
    # a water DEPTH per PERIOD (mm/day, cm/day, m_we/yr) — never a velocity (m/s): glacier mass balance counts, wind does not
    depth_rate = bool(re.fullmatch(r"(mm|cm|m|m_we|mwe)\s*/\s*(day|d|yr|year|a|month|mo|hr|h|timestep|step)", pref))
    for wL, wM, wT, wTh in dims:
        if (M, Th, wM, wTh) == (0, 0, 0, 0) and L == wL == 1 and T == 0 and wT == -1 and depth_rate:
            return True                                  # mm (per step) ~ mm/day
        if (M, Th, wM, wTh) == (1, 0, 0, 0) and L == -2 and wL == 1 and T in (0, wT) and wT in (0, -1) \
                and (depth_rate or (wT == 0 and pref.split("/")[0] in ("mm", "cm", "m", "m_we", "mwe"))):
            return True                                  # kg/m2 of water ~ mm (~ mm per step); never a velocity
    return False


def type_fits(section: str, source_kind: str | None, cid: str, facts: dict[str, dict]) -> bool:
    """A calibrated/default PARAMETER may only resolve to a canonical id whose target_type allows
    'parameter'; forcing / initial / boundary entries resolve to variables."""
    types = (facts.get(cid) or {}).get("types") or {"variable"}
    # a true model PARAMETER is one the KI calibrates or defaults (Ws, depth); a data-derived field
    # that merely lives in a parameter file (the LAI schedule, source_kind dataset_lookup) is a variable
    is_param = str(source_kind or "") in ("calibrated", "default")
    return ("parameter" in types) if is_param else ("variable" in types or not types)


def alias_index(root: Path) -> dict[str, str]:
    """lower-cased alias → canonical_id. Registry producers/consumers native names first, then the
    card generator's EXTRA_ALIASES (imported from the pipeline module so there is one table)."""
    key = str(root)
    if key in _ALIAS_CACHE:
        return _ALIAS_CACHE[key]
    idx: dict[str, str] = {}
    try:
        reg = _yaml().safe_load((Path(root) / "ata-kdt" / "artifacts" / "canonical_variable_registry.yaml")
                                .read_text(encoding="utf-8")) or {}
        # S0 (2026-09-21): a canonical id always names itself (water_table_depth must not become
        # hydraulic_head because a registry entry got there first), and only EXACT-confidence
        # registry names are aliases — the 'substring' entries are the junk (APSIM
        # "Wheat.Phenology.Zadok.Stage" as a water_surface_elevation producer)
        dropped = {str(x).lower() for x in (getattr(_card_gen_module(root), "DROPPED_ALIASES", set()) or set())}
        for cid in (reg.get("registry") or {}):
            idx[str(cid).lower()] = cid
        for cid, info in (reg.get("registry") or {}).items():
            for entry in (info.get("producers") or []) + (info.get("consumers") or []):
                if isinstance(entry, dict) and entry.get("confidence") in _EXACT_CONFIDENCES:
                    n = str(entry.get("native_name") or "").strip().lower()
                    if n and n not in idx and n not in dropped and n.replace(" ", "_") not in dropped:
                        idx[n] = cid
    except Exception:
        pass
    try:
        mod = _card_gen_module(root)
        dropped = {str(x).lower() for x in (getattr(mod, "DROPPED_ALIASES", set()) or set())}
        for alias, cid in (getattr(mod, "EXTRA_ALIASES", {}) or {}).items():
            if str(alias).lower() not in dropped:
                idx.setdefault(str(alias).lower(), cid)
    except Exception:
        pass
    _ALIAS_CACHE[key] = idx
    return idx


def _head(raw_name: str) -> str:
    """The dag name's HEAD: before any parenthesis / bracket / slash / comma, lower-cased."""
    return re.split(r"[\(\[/,]", str(raw_name or "").strip().lower())[0].strip()


def resolve_canonical(raw_name: str, idx: dict[str, str], side: str = "input") -> str | None:
    """The dag name's HEAD (before any parenthesis / slash / comma) must match a table alias
    EXACTLY (spaces and dashes count as underscores). No substring search: "c (baseflow curve
    exponent)" must not become baseflow, "depth (layer thickness)" must not become river_depth.
    A name that does not resolve stays unresolved — the fix is an alias in the table.
    side="output" (S0, 2026-09-21): a model's OUTPUT named by an ambiguous head (H, T, temperature,
    stage…) is not resolved from the global table at all."""
    if not raw_name:
        return None
    head = _head(raw_name)
    hkey = head.replace(" ", "_").replace("-", "_")
    if side == "output" and hkey in _AMBIGUOUS_OUTPUT_HEADS:
        return None
    if side != "output" and hkey in _OUTPUT_ONLY_ALIASES:
        return None            # "hmax" is SFINCS's flood depth OUTPUT; the same word as an input means something else
    if side not in ("output", "forcing") and hkey in _FORCING_ONLY_HEADS:
        return None            # an initial/boundary/parameter "temperature" is the model's own medium, not air
    for k in (head, head.replace(" ", "_").replace("-", "_")):     # the HEAD only (design point 2)
        if k and k in idx:
            return idx[k]
    return None


# ─── SKILL.md: the KI's STAGES (the design: every KI is dissected into pipeline stages) ────────────
def _md_tables(text: str) -> list[list[list[str]]]:
    """Every markdown table as a list of rows (cells stripped of backticks/whitespace/bold)."""
    tables, cur = [], []
    for line in text.splitlines():
        if line.strip().startswith("|"):
            cells = [re.sub(r"[`*]", "", c).strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            cur.append(cells)
        else:
            if cur:
                tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    return tables


def skill_stages(ki_root: Path) -> list[dict]:
    """The KI's pipeline stages as the SKILL states them: [{code, name, tools, text}] — listed, not mapped.
    Sources, merged by stage code: (1) tables whose header names a stage column (Stage | Name |
    Tools | Description…), (2) tables with an Input | Source | Tool shape (older KIs — each row is
    a stage-like statement), (3) tool paths in stage folders (`tools/s3_weather/x.py`, `s3_soil/x.py`)."""
    p = Path(ki_root) / "SKILL.md"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    stages: dict[str, dict] = {}

    def _get(code: str, name: str = "") -> dict:
        code = code.lower()
        st = stages.setdefault(code, {"code": code, "name": name, "tools": [], "text": ""})
        if name and not st["name"]:
            st["name"] = name
        return st

    stage_re = re.compile(r"^\s*(s\s?\d{1,2}[a-z]?(?=[_\s|]|$)|stage\s*\d{1,2}|\d{1,2})(?![\d.])", re.I)
    for t in _md_tables(text):
        if len(t) < 2:
            continue
        hdr = [h.lower() for h in t[0]]
        i_stage = next((i for i, h in enumerate(hdr) if h in ("stage", "#", "step") or h.startswith("stage")), None)
        i_tool = next((i for i, h in enumerate(hdr) if "tool" in h or "script" in h), None)
        i_name = next((i for i, h in enumerate(hdr) if h in ("name", "purpose", "stage name", "input", "description", "covers")), None)
        i_desc = next((i for i, h in enumerate(hdr) if h in ("description", "purpose", "source", "why", "covers") and i != i_name), None)
        if i_stage is not None and i_tool is not None:
            for r in t[1:]:
                if len(r) <= max(i_stage, i_tool):
                    continue
                m = stage_re.match(r[i_stage])
                if not m:
                    continue
                code = re.sub(r"\s+", "", m.group(1).lower())
                code = "s" + re.sub(r"^(stage|s)", "", code)
                st = _get(code, r[i_name] if i_name is not None and len(r) > i_name else "")
                st["tools"] += [x.strip() for x in re.split(r"[,;]| and ", r[i_tool]) if x.strip() and x.strip() not in ("—", "-", "(manual)")]
                st["text"] += " " + " ".join(r)
        elif i_name is not None and i_tool is not None and hdr[i_name] == "input":
            # older Input | Source | Tool table: stage code from the tool's folder
            for r in t[1:]:
                if len(r) <= i_tool:
                    continue
                m = re.search(r"\b(s\d{1,2})_", r[i_tool])
                code = m.group(1) if m else "s?" + _slug(r[i_name])[:12]
                st = _get(code, r[i_name])
                st["tools"] += [x.strip() for x in re.split(r"[,;]", r[i_tool]) if x.strip()]
                st["text"] += " " + " ".join(r)
    # tool paths in stage folders anywhere in the SKILL
    for m in re.finditer(r"(?:tools/)?(s\d{1,2})_([a-z0-9]+)/([A-Za-z0-9_]+\.py)", text):
        st = _get(m.group(1), m.group(2).replace("_", " "))
        tool = f"{m.group(1)}_{m.group(2)}/{m.group(3)}"
        if tool not in st["tools"]:
            st["tools"].append(tool)
        st["text"] += " " + m.group(2)
    out = []
    for code, st in stages.items():
        st["tools"] = list(dict.fromkeys(st["tools"]))
        out.append(st)
    def _key(st):
        m = re.match(r"s(\d+)", st["code"])
        return (0, int(m.group(1))) if m else (1, st["code"])
    return sorted(out, key=_key)


def _norm_id(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")


_DIR_CACHE: dict[str, dict[str, list[str]]] = {}


def model_ki_root(root: Path, model_id: str) -> Path:
    """<root>/models/<dir>/knowledge_infrastructure for a model id. The DB spells some ids with '-', '+'
    or spaces (HEC-RAS, SWAT+, WAVEWATCH III) while the folder uses '_' (HEC_RAS, SWAT_Plus,
    WAVEWATCH_III). Exact folder (symlinks included) first; else the ONE real folder whose normalised
    name matches. Ambiguous (two real folders normalise alike) or unknown → the exact path is returned
    unchanged (and will not exist). S0 round 2: a '+' folder never answers for a non-'+' id; '' is refused."""
    models = Path(root) / "models"
    mid = str(model_id or "").strip()
    if not mid:
        raise ValueError("model_ki_root: empty model id")
    exact = models / mid / "knowledge_infrastructure"
    if exact.is_dir():
        return exact
    key = str(models)
    if key not in _DIR_CACHE:
        m: dict[str, list[str]] = {}
        try:
            entries = sorted(models.iterdir())
        except OSError:
            entries = []
        for d in entries:
            try:
                if d.is_dir() and not d.is_symlink() and (d / "knowledge_infrastructure").is_dir():
                    m.setdefault(_norm_id(d.name.replace("+", "_plus")), []).append(d.name)
            except OSError:
                continue
        _DIR_CACHE[key] = m
    hits = _DIR_CACHE[key].get(_norm_id(mid.replace("+", "_plus")), [])
    if len(hits) == 1 and (("+" in hits[0]) == ("+" in mid)):
        return models / hits[0] / "knowledge_infrastructure"
    return exact


# ─── the model's inputs from its KI ──────────────────────────────────────────────────────────────
def model_inputs(root: Path, model_id: str, ki_root: Path | None = None) -> tuple[list[dict], str]:
    """(inputs, note). Reads <root>/models/<M>/knowledge_infrastructure/{dag.yaml,SKILL.md}. Empty list
    + a note when the dag is missing or unreadable (the caller decides what to do — no card fallback
    here, the owner retired the card as a planner source)."""
    ki = Path(ki_root) if ki_root else model_ki_root(root, model_id)
    try:
        dag = _yaml().safe_load((ki / "dag.yaml").read_text(encoding="utf-8")) or {}
    except Exception as e:
        return [], f"dag.yaml unreadable for {model_id}: {type(e).__name__}"
    ins = dag.get("inputs") or {}
    if not isinstance(ins, dict):
        return [], f"dag.yaml inputs is not a mapping for {model_id}"
    idx = alias_index(root)
    facts = canonical_facts(root)
    out: list[dict] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    for sec in list(DAG_SECTIONS) + [k for k in ins if k not in DAG_SECTIONS]:
        for e in ins.get(sec) or []:
            if not isinstance(e, dict):
                continue
            name = str(e.get("name") or e.get("local_name") or "").strip()
            if not name:
                continue
            cid = resolve_canonical(name, idx, side=sec)      # the dag section: forcing / initial_conditions / …
            if cid and unit_is_nonphysical(e.get("unit")):
                cid = None                    # "logical", "varies", "switch": a switch or a bundle, not a quantity
            if cid and not (unit_fits(e.get("unit"), cid, facts) and type_fits(sec, e.get("source_kind"), cid, facts)):
                rejected.append({"name": name, "section": sec, "unit": e.get("unit"), "rejected_id": cid})
                cid = None                    # an alias collision (e.g. VIC `Ws` -> wind_speed): not that quantity
            iid = cid or _slug(name)
            if iid in seen:
                # the dag lists a quantity once per mode (LAI as forcing / as a schedule): ONE input;
                # a mode the KI prepares itself wins the source_kind
                prev = next(o for o in out if o["id"] == iid)
                prev.setdefault("modes", [prev["name"]]).append(name)
                if e.get("source_kind") in KI_RESOLVED_SOURCE_KINDS:
                    prev["source_kind"] = e.get("source_kind")
                continue
            seen.add(iid)
            out.append({
                "id": iid, "name": name, "unit": str(e.get("unit") or ""), "category": sec,
                "dag_category": e.get("category"), "source_kind": e.get("source_kind"),
                "notes": e.get("notes"), "canonical_id": cid,
            })
    if rejected:
        out.append({"id": "_alias_rejections", "name": "(resolver guard)", "rejected": rejected, "category": "_meta"})
    return out, "ok"
