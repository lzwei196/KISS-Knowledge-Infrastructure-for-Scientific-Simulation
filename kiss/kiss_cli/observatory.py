"""Read-only projections of the KI library for the KI Observatory.

The Observatory never imports or executes code from a KI.  It renders facts
already present in ``dag.yaml``, diagnostics, visualization contracts and the
desktop's saved verification state.  This keeps an attractive overview from
becoming a second, less rigorous KI validator.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

try:
    import yaml
except ImportError:  # pragma: no cover - bundled by the desktop app
    yaml = None


DOMAINS = (
    {"id": "hydrology", "label": "Hydrology & water resources",
     "label_zh": "水文与水资源", "color": "#3977d4",
     "keywords": ("hydrolog", "rainfall-runoff", "watershed", "catchment", "river routing", "water resource")},
    {"id": "flood", "label": "Flood & hydrodynamics",
     "label_zh": "洪水与水动力", "color": "#19a7a2",
     "keywords": ("flood", "shallow-water", "shallow water", "hydrodynamic", "saint-venant", "inundation", "sph")},
    {"id": "groundwater", "label": "Groundwater & subsurface",
     "label_zh": "地下水与地下过程", "color": "#9b6b43",
     "keywords": ("groundwater", "subsurface", "porous", "darcy", "aquifer", "fracture", "richards")},
    {"id": "agriculture", "label": "Crop & agriculture",
     "label_zh": "作物与农业", "color": "#60a94d",
     "keywords": ("crop", "agricultur", "plant growth", "yield", "agro", "farm")},
    {"id": "land", "label": "Soil, land surface & ecosystems",
     "label_zh": "土壤、陆面与生态系统", "color": "#7c9b45",
     "keywords": ("land model", "land surface", "soil-plant", "ecosystem", "vegetation", "evapotranspiration", "terrestrial")},
    {"id": "cryosphere", "label": "Cryosphere & snow",
     "label_zh": "冰冻圈与积雪", "color": "#69aee8",
     "keywords": ("glacier", "ice sheet", "ice-sheet", "snow", "cryosphere", "firn")},
    {"id": "atmosphere", "label": "Atmosphere & climate",
     "label_zh": "大气与气候", "color": "#8d7ed8",
     "keywords": ("atmospher", "weather", "climate", "wrf", "nowcast", "meteorolog")},
    {"id": "ocean", "label": "Ocean, coast & waves",
     "label_zh": "海洋、海岸与波浪", "color": "#347bbd",
     "keywords": ("ocean", "coastal", "wave", "storm surge", "roms", "seawater")},
    {"id": "water_quality", "label": "Water quality & chemistry",
     "label_zh": "水质与化学", "color": "#2f9e78",
     "keywords": ("water quality", "reactive transport", "solute", "chemistry", "chemical", "nutrient", "phreeqc")},
    {"id": "biogeochemistry", "label": "Biogeochemistry & carbon",
     "label_zh": "生物地球化学与碳循环", "color": "#829d34",
     "keywords": ("biogeochem", "carbon", "nitrogen", "greenhouse gas", "photosynthesis", "n2o")},
    {"id": "geomorphology", "label": "Geomorphology & sediment",
     "label_zh": "地貌与泥沙", "color": "#c17c42",
     "keywords": ("geomorph", "sediment", "erosion", "landscape evolution", "delta", "debris", "landslide")},
    {"id": "wildfire", "label": "Wildfire & disturbance",
     "label_zh": "野火与扰动", "color": "#d65e45",
     "keywords": ("wildfire", "fire spread", "fire-spread", "combust", "fuel model")},
    {"id": "geoscience", "label": "Geophysics & geoscience",
     "label_zh": "地球物理与地学", "color": "#a05d9e",
     "keywords": ("geophys", "geolog", "geothermal", "inversion", "electromagnetic", "seismic")},
    {"id": "infrastructure", "label": "Earth-system frameworks & infrastructure",
     "label_zh": "地球系统框架与基础设施", "color": "#667280",
     "keywords": ("framework", "coupled", "infrastructure", "interface", "assimilation", "network", "bmi", "esmf")},
)

_DOMAIN_BY_ID = {item["id"]: item for item in DOMAINS}

# Model names are stronger evidence than a word buried in a broad model's
# description.  This small routing table covers ambiguous families; remaining
# packages are classified from their own scientific reference and SKILL text.
_NAME_DOMAIN = {
    "ADCIRC": "ocean", "ANUGA": "flood", "APEX": "agriculture",
    "APSIM": "agriculture", "AquaCrop": "agriculture", "CE_QUAL_W2": "water_quality",
    "DSSAT": "agriculture", "Delft3D": "flood", "DNDC": "biogeochemistry",
    "EPIC": "agriculture", "MONICA": "agriculture", "RZWQM2": "agriculture",
    "WOFOST": "agriculture", "PyAEZ": "agriculture", "Daisy": "agriculture",
    "CaMa_Flood": "flood", "CAESAR_Lisflood": "geomorphology",
    "DLBreach": "flood", "DualSPHysics": "flood", "GeoClaw": "flood",
    "HEC_RAS": "flood", "SFINCS": "flood", "TELEMAC_MASCARET": "flood",
    "MODFLOW6": "groundwater", "FloPy": "groundwater", "GSFLOW": "groundwater",
    "ParFlow": "groundwater", "PFLOTRAN": "groundwater", "PorePy": "groundwater",
    "dfnWorks": "groundwater", "DuMux": "groundwater", "OpenGeoSys": "groundwater",
    "Alpine3D": "cryosphere", "CISM": "cryosphere", "COSIPY": "cryosphere",
    "Elmer_Ice": "cryosphere", "FSM2": "cryosphere", "ISSM": "cryosphere",
    "OGGM": "cryosphere", "PISM": "cryosphere", "SNOWPACK": "cryosphere",
    "icepack": "cryosphere", "openAMUNDSEN": "cryosphere",
    "WRF": "atmosphere", "Climate_Projection": "atmosphere", "pySTEPS": "atmosphere",
    "ROMS": "ocean", "MOM6": "ocean", "SWAN": "ocean", "COAWST": "ocean",
    "WASP": "water_quality", "GLM": "water_quality", "OpenHydroQual": "water_quality",
    "PHREEQC": "water_quality", "BIOME_BGC": "biogeochemistry", "DayCent": "biogeochemistry",
    "FATES": "biogeochemistry", "LDNDC": "biogeochemistry", "LPJ_GUESS": "biogeochemistry",
    "LPJmL": "biogeochemistry", "QUINCY": "biogeochemistry", "ELM": "land",
    "CLM5___CTSM": "land", "CLASSIC": "land", "Noah_MP": "land",
    "SHAW": "land", "SWAP": "land", "GEOtop": "land",
    "HydroTrend": "geomorphology", "Landlab": "geomorphology", "PyDeltaRCM": "geomorphology",
    "TRIGRS": "geomorphology", "pyBadlands": "geomorphology",
    "Cell2Fire": "wildfire", "ELMFIRE": "wildfire", "ForeFire": "wildfire",
    "SimFire": "wildfire", "GemPy": "geoscience", "GEOPHIRES": "geoscience",
    "SimPEG": "geoscience", "pyGIMLi": "geoscience",
    "BMI": "infrastructure", "DART": "infrastructure", "ESMF": "infrastructure",
    "PyMT": "infrastructure", "OpenFOAM": "infrastructure", "WSIMOD": "infrastructure",
    "CREST": "hydrology", "CRHM": "hydrology", "CWatM": "hydrology",
    "DHSVM": "hydrology", "EF5": "hydrology", "GR4J___airGR": "hydrology",
    "HEC_HMS": "hydrology", "HYPE": "hydrology", "HydroCNHS": "hydrology",
    "KINEROS2": "hydrology", "LISFLOOD": "hydrology", "Lohmann_Routing": "hydrology",
    "MARRMoT": "hydrology", "MOSART": "hydrology", "PCR_GLOBWB_2": "hydrology",
    "PIHM": "hydrology", "PRMS": "hydrology", "RAPID": "hydrology",
    "RHESSys": "hydrology", "Raven": "hydrology", "Ribasim": "hydrology",
    "SUMMA": "hydrology", "SWAT_Plus": "hydrology", "SuperflexPy": "hydrology",
    "TOPMODEL": "hydrology", "TopoFlow": "hydrology", "VELMA": "hydrology",
    "VIC": "hydrology", "WRF_Hydro": "hydrology", "mHM": "hydrology",
    "mizuRoute": "hydrology", "tRIBS": "hydrology", "wflow": "hydrology",
}

_SEMANTICS = {
    "weather": ("precip", "rain", "temperature", "tmax", "tmin", "radiation", "humidity", "wind", "weather", "forcing"),
    "runoff": ("runoff", "discharge", "streamflow", "river flow", "outflow", "baseflow"),
    "flood": ("flood", "inundation", "water depth", "water level", "stage"),
    "terrain": ("dem", "terrain", "elevation", "topography", "slope", "mesh", "grid", "geometry"),
    "soil": ("soil", "hydraulic conductivity", "porosity", "infiltration"),
    "groundwater": ("groundwater", "aquifer", "hydraulic head", "water table", "recharge"),
    "vegetation": ("vegetation", "land cover", "lai", "canopy", "plant"),
    "crop": ("crop", "cultivar", "phenology", "yield", "planting", "harvest"),
    "snow_ice": ("snow", "ice", "glacier", "swe", "melt"),
    "sediment": ("sediment", "erosion", "bedload", "suspended load"),
    "water_quality": ("water quality", "nutrient", "solute", "concentration", "nitrate", "phosph", "oxygen"),
    "ocean_wave": ("ocean", "wave", "tide", "surge", "sea level", "current"),
    "carbon": ("carbon", "co2", "n2o", "methane", "biomass", "respiration"),
}


def _text(value, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _items(value) -> list[dict]:
    if isinstance(value, list):
        return [item if isinstance(item, dict) else {"name": _text(item)} for item in value]
    if isinstance(value, dict):
        out = []
        for key, val in value.items():
            if isinstance(val, list):
                out.extend(_items(val))
            elif isinstance(val, dict):
                out.append({"name": key, **val})
        return out
    return []


def _input_items(doc: dict) -> list[dict]:
    raw = doc.get("inputs") or {}
    if not isinstance(raw, dict):
        return _items(raw)
    out = []
    for group, values in raw.items():
        if str(group).startswith("_"):
            continue
        for item in _items(values):
            out.append({"group": group, **item})
    return out


def _process_items(doc: dict) -> list[dict]:
    raw = doc.get("processes") or {}
    if isinstance(raw, dict):
        modules = raw.get("modules") or []
        return _items(modules)
    return _items(raw)


def _semantic_tags(items: list[dict]) -> set[str]:
    text = " ".join(_text(item, 1200).lower() for item in items)
    return {tag for tag, words in _SEMANTICS.items() if any(word in text for word in words)}


def classify(ki) -> tuple[str, str]:
    """Return a domain and the evidence used for that classification."""
    if ki.name in _NAME_DOMAIN:
        return _NAME_DOMAIN[ki.name], "curated library family"
    reference = _text((ki.meta or {}).get("reference"), 3000).lower()
    skill = ""
    try:
        skill = ki.skill.read_text(encoding="utf-8", errors="replace")[:7000].lower()
    except (AttributeError, OSError):
        pass
    hay = f"{ki.name.lower()} {reference} {skill}"
    scores = Counter()
    for domain in DOMAINS:
        for word in domain["keywords"]:
            if word in hay:
                scores[domain["id"]] += 3 if word in reference else 1
    if scores:
        winner = max(scores, key=lambda key: (scores[key], -list(_DOMAIN_BY_ID).index(key)))
        return winner, "scientific reference and KI documentation"
    return "infrastructure", "generic Earth-system KI"


def _triplet_count(ki) -> int:
    path = ki.triplets
    if not path:
        return 0
    try:
        if path.suffix in {".yaml", ".yml"} and yaml is not None:
            raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or []
            if isinstance(raw, dict):
                for key in ("triplets", "diagnostics", "items"):
                    if isinstance(raw.get(key), list):
                        return len(raw[key])
            return len(raw) if isinstance(raw, list) else 0
        return len(re.findall(r"^#{2,4}\s+|^\s*-\s+symptom\s*:",
                              path.read_text(encoding="utf-8", errors="replace"), re.MULTILINE))
    except (OSError, ValueError):
        return 0


def _contract(ki) -> dict:
    candidates = (ki.root / "docs" / "visualization_contract.yaml",
                  ki.root / "visualization_contract.yaml")
    path = next((item for item in candidates if item.is_file()), None)
    if path is None or yaml is None:
        return {"present": False, "path": None, "views": []}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return {"present": True, "path": path.relative_to(ki.root).as_posix(),
                "valid": False, "views": []}
    values = raw.get("visualizations") if isinstance(raw, dict) else []
    views = []
    for index, item in enumerate(_items(values)[:24]):
        views.append({
            "id": _text(item.get("id") or f"view-{index + 1}", 80),
            "title": _text(item.get("title") or item.get("name") or f"View {index + 1}", 160),
            "kind": _text(item.get("kind") or item.get("type") or "plot", 40).lower(),
            "description": _text(item.get("description"), 500),
            "tool": _text(item.get("tool") or item.get("renderer"), 240),
        })
    return {"present": True, "valid": True,
            "path": path.relative_to(ki.root).as_posix(), "views": views}


def _ki_facts(ki, status: dict) -> dict:
    doc = ki.dag_doc
    inputs = _input_items(doc)
    processes = _process_items(doc)
    outputs = _items(doc.get("outputs") or [])
    tools = []
    try:
        tools = sorted(path.relative_to(ki.root).as_posix()
                       for path in (ki.root / "tools").rglob("*.py") if path.is_file())
    except OSError:
        pass
    triplets = _triplet_count(ki)
    complexity_raw = len(inputs) + len(processes) * 2 + len(outputs) + min(triplets, 100) / 4 + len(tools)
    domain, domain_evidence = classify(ki)
    return {
        "id": ki.name, "name": ki.name, "domain": domain,
        "domain_evidence": domain_evidence,
        "reference": _text((ki.meta or {}).get("reference"), 360),
        "language": (ki.meta or {}).get("language"),
        "ki_class": (ki.meta or {}).get("ki_class"),
        "state": status.get("state") or "setup",
        "verified": bool(status.get("can_run")),
        "status_label": status.get("label") or "Setup needed",
        "complexity": round(1 + math.log2(max(1, complexity_raw)), 2),
        "counts": {"inputs": len(inputs), "processes": len(processes),
                   "outputs": len(outputs), "tools": len(tools), "diagnostics": triplets},
        "input_tags": sorted(_semantic_tags(inputs)),
        "output_tags": sorted(_semantic_tags(outputs)),
        "contract": _contract(ki),
    }


def atlas(catalog, status_for: Callable) -> dict:
    """Build the 14-region local library atlas and evidence-backed links."""
    nodes = [_ki_facts(ki, status_for(ki)) for ki in catalog]
    by_domain = defaultdict(list)
    for node in nodes:
        by_domain[node["domain"]].append(node)
    domains = []
    for item in DOMAINS:
        members = sorted(by_domain[item["id"]], key=lambda row: row["name"].lower())
        domains.append({**{key: item[key] for key in ("id", "label", "label_zh", "color")},
                        "count": len(members), "verified": sum(row["verified"] for row in members)})

    # Keep links legible: coupling (an output of A matches an input of B) is
    # stronger than merely sharing forcing.  Every edge carries its evidence.
    candidates = []
    for index, left in enumerate(nodes):
        li, lo = set(left["input_tags"]), set(left["output_tags"])
        for right in nodes[index + 1:]:
            ri, ro = set(right["input_tags"]), set(right["output_tags"])
            forward, reverse = lo & ri, ro & li
            shared = li & ri
            if forward or reverse:
                direction = (left, right, forward) if len(forward) >= len(reverse) else (right, left, reverse)
                candidates.append({"source": direction[0]["id"], "target": direction[1]["id"],
                                   "kind": "coupling", "weight": 5 + len(direction[2]),
                                   "evidence": sorted(direction[2])})
            elif len(shared) >= 2 and left["domain"] == right["domain"]:
                candidates.append({"source": left["id"], "target": right["id"],
                                   "kind": "shared_data", "weight": len(shared),
                                   "evidence": sorted(shared)})
    candidates.sort(key=lambda row: (-row["weight"], row["source"], row["target"]))
    degree = Counter()
    edges = []
    for edge in candidates:
        if degree[edge["source"]] >= 4 or degree[edge["target"]] >= 4:
            continue
        edges.append(edge)
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
        if len(edges) >= 220:
            break

    # The Observatory opens at domain level.  Sending a compact aggregate here
    # keeps that first view honest and legible: the UI does not need to draw
    # hundreds of KI-to-KI lines just to explain that two scientific families
    # can exchange data.  Detailed evidence remains on the original edges and
    # appears only after the user focuses a KI.
    node_domain = {node["id"]: node["domain"] for node in nodes}
    aggregate: dict[tuple[str, str], dict] = {}
    for edge in edges:
        source_domain = node_domain.get(edge["source"])
        target_domain = node_domain.get(edge["target"])
        if not source_domain or not target_domain or source_domain == target_domain:
            continue
        pair = tuple(sorted((source_domain, target_domain)))
        item = aggregate.setdefault(pair, {
            "source": pair[0], "target": pair[1], "count": 0,
            "coupling": 0, "shared_data": 0, "evidence": set(),
        })
        item["count"] += 1
        item[edge["kind"]] = item.get(edge["kind"], 0) + 1
        item["evidence"].update(edge["evidence"])
    domain_edges = []
    for item in aggregate.values():
        domain_edges.append({
            **{key: value for key, value in item.items() if key != "evidence"},
            "evidence": sorted(item["evidence"]),
        })
    domain_edges.sort(key=lambda row: (-row["coupling"], -row["count"],
                                       row["source"], row["target"]))
    return {
        "version": 1, "title": "KI Observatory", "paper_baseline": 119,
        "paper_domains": 14, "local_count": len(nodes), "domains": domains,
        "nodes": nodes, "edges": edges, "domain_edges": domain_edges,
        "method": ("Domains use the KISS paper's 14-domain framing and local KI scientific metadata. "
                   "Relations are computed only from matching declared input/output semantics."),
    }


_DOMAIN_STORY = {
    "hydrology": ("water moving through a catchment", "流域中的水循环",
                  "streamflow, storage and water-balance results", "径流、蓄水与水量平衡结果"),
    "flood": ("river and floodplain water", "河道与洪泛区水体",
              "discharge, water level and flood extent", "流量、水位与淹没范围"),
    "groundwater": ("water below the land surface", "地下水系统",
                    "water heads, fluxes and subsurface states", "水头、通量与地下状态"),
    "agriculture": ("the soil–crop–atmosphere system", "土壤—作物—大气系统",
                    "crop growth, yield and resource use", "作物生长、产量与资源利用结果"),
    "land": ("the land surface and ecosystem", "陆面与生态系统",
             "surface fluxes, soil states and ecosystem response", "地表通量、土壤状态与生态响应"),
    "cryosphere": ("snow and ice", "积雪与冰体",
                   "snow, ice and melt evolution", "积雪、冰体与融化过程结果"),
    "atmosphere": ("the atmosphere", "大气系统",
                   "weather and climate fields through time", "随时间变化的天气与气候场"),
    "ocean": ("the ocean and coast", "海洋与海岸系统",
              "currents, levels, waves and coastal response", "流场、水位、波浪与海岸响应"),
    "water_quality": ("water and its dissolved or suspended constituents", "水体及其中的物质",
                      "concentrations, loads and chemical state", "浓度、负荷与化学状态"),
    "biogeochemistry": ("carbon, nutrients and living processes", "碳、养分与生物过程",
                        "stocks, fluxes and biogeochemical response", "储量、通量与生物地球化学响应"),
    "geomorphology": ("sediment and evolving landforms", "泥沙与演变中的地貌",
                      "erosion, transport and landform change", "侵蚀、输运与地貌变化"),
    "wildfire": ("fuel, fire and the surrounding landscape", "燃料、火行为与周边景观",
                 "fire spread, intensity and disturbance", "火势传播、强度与扰动结果"),
    "geoscience": ("the Earth's physical structure and fields", "地球物理结构与场",
                   "physical fields, inversions and subsurface interpretation", "物理场、反演与地下解释"),
    "infrastructure": ("coupled scientific components", "相互耦合的科学组件",
                       "coordinated states and exchange across components", "组件间协调的状态与交换结果"),
}

_PROCESS_PHASE_WORDS = (
    ("prepare", ("read", "load", "input", "forcing", "boundary", "initialize",
                 "initialise", "setup", "config", "grid", "mesh", "parameter",
                 "remap", "convert", "extract", "prepare")),
    ("connect", ("route", "routing", "exchange", "couple", "link", "transfer",
                 "confluence", "network", "aggregate")),
    ("assess", ("validate", "check", "diagnostic", "score", "evaluate",
                "calibrat", "compare", "quality")),
    ("present", ("write", "output", "export", "plot", "render", "summary",
                 "report", "visual")),
)


def _process_story_phase(node: dict) -> str:
    text = " ".join(str(node.get(key) or "") for key in (
        "label", "detail", "role", "applicability")).lower()
    for phase, words in _PROCESS_PHASE_WORDS:
        if any(word in text for word in words):
            return phase
    return "simulate"


def _story_projection(facts: dict, graph_nodes: list[dict], input_ids: list[str],
                      process_ids: list[str], output_ids: list[str]) -> dict:
    """Translate technical DAG nodes into a small scientific narrative.

    The raw identifiers remain available in ``graph`` for inspection, but the
    default Observatory view should explain the science rather than restyle a
    source-code listing.
    """
    subject, subject_zh, result, result_zh = _DOMAIN_STORY.get(
        facts["domain"], ("the scientific system", "科学系统",
                          "model-ready scientific results", "可使用的科学结果"))
    by_id = {node["id"]: node for node in graph_nodes}
    grouped: dict[str, list[str]] = defaultdict(list)
    for node_id in process_ids:
        node = by_id.get(node_id)
        if node:
            grouped[_process_story_phase(node)].append(node_id)

    def phase(phase_id: str, kind: str, title: str, title_zh: str,
              summary: str, summary_zh: str, node_ids: list[str], icon: str) -> dict:
        return {
            "id": phase_id, "kind": kind, "title": title, "title_zh": title_zh,
            "summary": summary, "summary_zh": summary_zh, "icon": icon,
            "node_ids": node_ids, "technical_count": len(node_ids),
        }

    phases = [phase(
        "evidence", "input", "Bring together the evidence", "汇集研究所需信息",
        f"Collect the observations, drivers and choices needed to describe {subject}.",
        f"收集用于描述{subject_zh}的观测、驱动数据和必要选择。",
        input_ids, "data")]
    if grouped["prepare"]:
        phases.append(phase(
            "model_world", "process", "Build the model world", "构建模型中的研究对象",
            f"Turn source material into a model-ready representation of {subject}.",
            f"把原始资料转换成模型可以计算的{subject_zh}。",
            grouped["prepare"], "world"))
    if grouped["simulate"] or not process_ids:
        phases.append(phase(
            "evolve", "process", "Let the system evolve", "推演系统如何变化",
            f"Apply the governing scientific rules and advance {subject} through time.",
            f"应用科学规律，逐步推演{subject_zh}随时间的变化。",
            grouped["simulate"], "engine"))
    if grouped["connect"]:
        phases.append(phase(
            "connect", "process", "Connect places and components", "连接不同位置与组件",
            "Move information between locations or coupled parts without hiding the exchange.",
            "在不同位置或耦合组件之间传递信息，并保留交换过程。",
            grouped["connect"], "network"))
    if grouped["assess"]:
        phases.append(phase(
            "scientific_assessment", "process", "Assess the simulated behaviour", "评估模拟行为",
            "Compare, score or diagnose the simulated behaviour before accepting it.",
            "在接受结果前，对模拟行为进行比较、评分或诊断。",
            grouped["assess"], "assess"))
    phases.append(phase(
        "trust_gate", "verification", "Pass the trust gate", "通过可信检查",
        "Check installation, required evidence and scientific consistency before continuing.",
        "检查软件、所需证据和科学一致性，只有通过后才继续。",
        ["verification"], "gate"))
    result_nodes = output_ids + grouped["present"]
    phases.append(phase(
        "results", "output", "Make the result usable", "形成可使用的结果",
        f"Organize the simulation into {result} that people can inspect and reuse.",
        f"把模拟整理为可查看、可复用的{result_zh}。",
        result_nodes, "result"))
    return {
        "version": 1, "source": "scientific_projection",
        "phases": phases,
        "technical_node_count": len(input_ids) + len(process_ids) + len(output_ids) + 1,
        "note": ("User-facing phases are inferred from declared DAG semantics. "
                 "Exact identifiers remain in the technical view."),
    }


def model(ki, status: dict) -> dict:
    """Return one generic production line plus optional specialized views."""
    facts = _ki_facts(ki, status)
    doc = ki.dag_doc
    inputs = _input_items(doc)
    processes = _process_items(doc)
    outputs = _items(doc.get("outputs") or [])
    graph_nodes, graph_edges = [], []

    def add(node_id: str, kind: str, label: str, detail: str = "", **extra) -> None:
        graph_nodes.append({"id": node_id, "kind": kind, "label": _text(label, 180),
                            "detail": _text(detail, 800), **extra})

    grouped = defaultdict(list)
    for item in inputs:
        grouped[item.get("group") or "inputs"].append(item)
    input_ids = []
    for index, (group, values) in enumerate(grouped.items()):
        node_id = f"input-{index + 1}"
        names = [_text(v.get("name") or v.get("var"), 100) for v in values]
        add(node_id, "input", str(group).replace("_", " ").title(),
            " · ".join(name for name in names[:8] if name), count=len(values), items=names[:40])
        input_ids.append(node_id)

    process_ids = []
    for index, item in enumerate(processes[:18]):
        node_id = f"process-{index + 1}"
        add(node_id, "process", item.get("name") or f"Process {index + 1}",
            item.get("brief") or item.get("description"), role=_text(item.get("role"), 80),
            applicability=_text(item.get("applicability"), 240), order=index + 1)
        process_ids.append(node_id)
    add("verification", "verification", "KI verification gate",
        f"{facts['counts']['diagnostics']} diagnostic recovery mechanisms · preflight_check.py")

    output_ids = []
    for index, item in enumerate(outputs[:18]):
        node_id = f"output-{index + 1}"
        add(node_id, "output", item.get("var") or item.get("name") or f"Output {index + 1}",
            item.get("description"), unit=_text(item.get("unit"), 80),
            emitted_in=_text(item.get("emitted_in"), 200))
        output_ids.append(node_id)

    first_process = process_ids[0] if process_ids else "verification"
    graph_edges.extend({"source": source, "target": first_process} for source in input_ids)
    graph_edges.extend({"source": process_ids[i], "target": process_ids[i + 1]}
                       for i in range(len(process_ids) - 1))
    if process_ids:
        graph_edges.append({"source": process_ids[-1], "target": "verification"})
    graph_edges.extend({"source": "verification", "target": target} for target in output_ids)

    # The Observatory opens with the scientific story, not every implementation
    # helper.  Integrators and optional validators remain available in the full
    # DAG, while the first view keeps the model's declared module order.
    secondary_roles = {"integrator", "optional_module", "validator", "utility", "helper"}
    primary_process_ids = [
        node["id"] for node in graph_nodes
        if node["kind"] == "process" and str(node.get("role") or "").lower() not in secondary_roles
    ]
    if not primary_process_ids:
        primary_process_ids = list(process_ids)
    if len(primary_process_ids) > 8:
        primary_process_ids = primary_process_ids[:7] + [primary_process_ids[-1]]
    visible = set(primary_process_ids)
    overview = {
        "input_ids": input_ids,
        "process_ids": primary_process_ids,
        "hidden_process_ids": [item for item in process_ids if item not in visible],
        "verification_id": "verification",
        "output_ids": output_ids,
    }
    story = _story_projection(facts, graph_nodes, input_ids, process_ids, output_ids)

    return {**facts, "graph": {"nodes": graph_nodes, "edges": graph_edges},
            "overview": overview, "story": story,
            "safety": {"read_only": True, "executes_ki_code": False,
                       "sources": ["dag.yaml", "diagnostics", "visualization_contract.yaml",
                                   "saved machine verification"]}}
