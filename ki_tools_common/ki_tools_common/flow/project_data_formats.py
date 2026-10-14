"""Explicit, bounded model-input formats for reviewed project data adapters.

These host parsers establish file structure, never scientific correctness or
model readiness. They do not import PCSE, execute metadata, or modify artifacts.
The caller binds contracts to a reviewed plan and authenticates run receipts.
"""
from __future__ import annotations

import ast
import csv
import datetime as dt
import hashlib
import io
import math
from pathlib import Path, PurePosixPath
import re

import yaml

POLICY = "project-data-explicit-formats-v1"
FORMAT_IDS = {"pcse_weather_csv_v1", "pcse_agromanagement_yaml_v1"}
WEATHER_COLUMNS = ("DAY", "IRRAD", "TMIN", "TMAX", "VAP", "WIND", "RAIN", "SNOWDEPTH")
SITE_TEXT = {"Country", "Station", "Description", "Source", "Contact"}
SITE_NUMERIC = {"Longitude", "Latitude", "Elevation", "AngstromA", "AngstromB"}
SITE_KEYS = SITE_TEXT | SITE_NUMERIC | {"HasSunshine"}
MAX_WEATHER_BYTES = 32 * 1024 * 1024
MAX_WEATHER_ROWS = 200_000
MAX_METADATA_BYTES = 64 * 1024
MAX_METADATA_LINES = 64
MAX_YAML_BYTES = 256 * 1024
MAX_YAML_EVENTS = 4096
MAX_YAML_DEPTH = 16
MAX_SCALAR_CHARS = 4096


def source_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _date(value, compact=False):
    pattern = r"[0-9]{8}" if compact else r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError("Date does not match the declared canonical format")
    result = dt.datetime.strptime(value, "%Y%m%d" if compact else "%Y-%m-%d").date()
    # strftime is platform-dependent for years below 1000; format explicitly.
    canonical = f"{result.year:04d}{result.month:02d}{result.day:02d}" if compact else result.isoformat()
    if value != canonical:
        raise ValueError("Date is not canonical")
    return result


def _contract(contract):
    if (not isinstance(contract, dict) or not isinstance(contract.get("format"), str)
            or contract["format"] not in FORMAT_IDS):
        raise ValueError("Unsupported explicit project-data format")
    option = "date_format" if contract["format"] == "pcse_weather_csv_v1" else "campaign_start"
    if set(contract) != {"output_id", "path", "format", option}:
        raise ValueError("Explicit output format has missing or unknown fields")
    if (not isinstance(contract["output_id"], str) or not contract["output_id"].strip()
            or len(contract["output_id"]) > 128):
        raise ValueError("Explicit output format needs a short nonempty output_id")
    value = contract["path"]
    if (not isinstance(value, str) or len(value) > 1024 or "\\" in value
            or any(char in value for char in (":", "$", "\x00", "\r", "\n"))):
        raise ValueError("Explicit output format needs a literal project-relative path")
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value or len(path.parts) < 2
            or path.parts[0] not in {"outputs", "artifacts"}
            or any(part in {"", ".", ".."} for part in path.parts)):
        raise ValueError("Explicit output path must remain within outputs/ or artifacts/")
    if option == "date_format":
        if contract[option] != "%Y%m%d" or path.suffix.lower() != ".csv":
            raise ValueError("PCSE weather v1 requires .csv and date_format=%Y%m%d")
    else:
        _date(contract[option])
        if path.suffix.lower() not in {".yaml", ".yml"}:
            raise ValueError("PCSE agromanagement v1 requires .yaml or .yml")


def validate_contract(contract) -> None:
    """Validate the exact declared format without opening or parsing any file."""
    _contract(contract)


def _read(path, limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("Explicit data output must be an ordinary unshared file")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError("Explicit data output is empty or exceeds its format size limit")
    text = raw.decode("utf-8-sig")
    if "\x00" in text:
        raise ValueError("Explicit data output contains binary NUL content")
    return raw, text


def _metadata(lines):
    if not lines or lines[0].rstrip("\r\n") != "## Site Characteristics":
        raise ValueError("PCSE weather requires its Site Characteristics preamble")
    metadata, total = {}, len(lines[0].encode("utf-8"))
    for index, line in enumerate(lines[1:], start=1):
        total += len(line.encode("utf-8"))
        if total > MAX_METADATA_BYTES or index >= MAX_METADATA_LINES:
            raise ValueError("PCSE weather metadata exceeds its bounded size")
        body = line.rstrip("\r\n")
        if re.fullmatch(r"## Daily weather observations(?: \([^()\r\n]{0,200}\))?", body):
            if set(metadata) != SITE_KEYS:
                raise ValueError("PCSE weather metadata needs exactly the eleven required site fields")
            return metadata, index + 1
        # Match PCSE's semicolon-separated literal assignments. Never evaluate
        # Python code; even strings containing semicolons are unsupported by
        # the native CSV reader and are deliberately refused here.
        for statement in body.split(";"):
            if statement.count("=") != 1:
                raise ValueError("PCSE metadata requires exactly one equals sign per assignment")
            tree = ast.parse(statement.strip(), mode="exec")
            if (len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assign)
                    or len(tree.body[0].targets) != 1
                    or not isinstance(tree.body[0].targets[0], ast.Name)):
                raise ValueError("PCSE metadata permits only simple literal assignments")
            assignment = tree.body[0]
            key = assignment.targets[0].id
            if key not in SITE_KEYS or key in metadata:
                raise ValueError("PCSE metadata contains an unknown or duplicate field")
            value = ast.literal_eval(assignment.value)
            if key in SITE_TEXT:
                if not isinstance(value, str) or len(value) > MAX_SCALAR_CHARS:
                    raise ValueError("PCSE text metadata must be a bounded string")
            elif key in SITE_NUMERIC:
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError("PCSE numeric metadata must be finite")
            elif type(value) is not bool:
                raise ValueError("PCSE HasSunshine must be a boolean")
            metadata[key] = value
    raise ValueError("PCSE weather has no daily observations marker")


def _weather(text):
    lines = text.splitlines(keepends=True)
    metadata, start = _metadata(lines)
    if not -180 <= metadata["Longitude"] <= 180 or not -90 < metadata["Latitude"] < 90:
        raise ValueError("PCSE site coordinates are outside the supported range")
    a, b = abs(metadata["AngstromA"]), abs(metadata["AngstromB"])
    if not (.1 <= a <= .4 and .3 <= b <= .7 and .6 <= a + b <= .9):
        raise ValueError("PCSE Angstrom coefficients violate the native provider bounds")
    rows = csv.reader(io.StringIO("".join(lines[start:]), newline=""), strict=True)
    if next(rows, None) != list(WEATHER_COLUMNS):
        raise ValueError("PCSE weather requires the exact eight-column header")
    count, first, previous, missing_snow = 0, None, None, 0
    for row in rows:
        count += 1
        if count > MAX_WEATHER_ROWS:
            raise ValueError("PCSE weather exceeds its row limit")
        if len(row) != len(WEATHER_COLUMNS) or any(len(field) > 128 for field in row):
            raise ValueError("PCSE weather row has an invalid width or oversized field")
        day = _date(row[0], compact=True)
        if previous is not None and day != previous + dt.timedelta(days=1):
            raise ValueError("PCSE weather dates must be unique, ordered and daily-contiguous")
        values = []
        for key, token in zip(WEATHER_COLUMNS[1:], row[1:]):
            if key == "SNOWDEPTH" and token.strip().lower() == "nan":
                missing_snow += 1
                values.append(None)
                continue
            if "\r" in token or "\n" in token:
                raise ValueError("PCSE weather numeric fields must occupy one line")
            value = float(token)
            if not math.isfinite(value):
                raise ValueError("PCSE weather requires finite numeric fields except missing snow depth")
            values.append(value)
        irrad, tmin, tmax, vap, wind, rain, snow = values
        if tmin > tmax or min(irrad, vap, wind, rain) < 0 or (snow is not None and snow < 0):
            raise ValueError("PCSE weather has inverted temperatures or negative radiation, vapour, wind, rain or snow")
        if metadata["HasSunshine"] and irrad > 24:
            raise ValueError("PCSE sunshine duration must be between zero and 24 hours")
        first = first or day
        previous = day
    if not count:
        raise ValueError("PCSE weather has no records")
    return {"row_count": count, "first_date": first.isoformat(), "last_date": previous.isoformat(),
            "daily_contiguous": True, "columns": list(WEATHER_COLUMNS),
            "metadata_fields": sorted(metadata), "snowdepth_missing_count": missing_snow,
            "has_sunshine": metadata["HasSunshine"], "implicit_selection": False}


class _UniqueSafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            if not isinstance(key_node, yaml.ScalarNode):
                raise ValueError("Agromanagement mapping keys must be scalar")
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, (str, dt.date)) or key in result:
                raise ValueError("Agromanagement contains an invalid or duplicate key")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _agro(text, expected_start):
    depth = documents = 0
    allowed_tags = {"tag:yaml.org,2002:" + name for name in
                    ("map", "seq", "str", "int", "float", "bool", "null", "timestamp")}
    for count, event in enumerate(yaml.parse(text, Loader=yaml.SafeLoader), start=1):
        if count > MAX_YAML_EVENTS:
            raise ValueError("Agromanagement exceeds its parser event limit")
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None) is not None:
            raise ValueError("Agromanagement aliases and anchors are unsupported")
        if getattr(event, "tag", None) not in allowed_tags | {None}:
            raise ValueError("Agromanagement custom YAML tags are unsupported")
        if isinstance(event, yaml.ScalarEvent) and len(event.value) > MAX_SCALAR_CHARS:
            raise ValueError("Agromanagement scalar exceeds its size limit")
        if isinstance(event, yaml.DocumentStartEvent):
            documents += 1
        if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
            if depth > MAX_YAML_DEPTH:
                raise ValueError("Agromanagement exceeds its nesting limit")
        elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1
    if documents != 1:
        raise ValueError("Agromanagement requires exactly one YAML document")
    data = yaml.load(text, Loader=_UniqueSafeLoader)
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict) or len(data[0]) != 1:
        raise ValueError("Agromanagement v1 requires exactly one campaign")
    campaign_start, campaign = next(iter(data[0].items()))
    if type(campaign_start) is not dt.date or campaign_start != _date(expected_start):
        raise ValueError("Agromanagement campaign date differs from the approved date")
    if not isinstance(campaign, dict) or set(campaign) != {"CropCalendar", "TimedEvents", "StateEvents"}:
        raise ValueError("Agromanagement requires the exact campaign structure")
    if campaign["TimedEvents"] is not None or campaign["StateEvents"] is not None:
        raise ValueError("Agromanagement v1 supports no timed or state events")
    calendar = campaign["CropCalendar"]
    fields = {"crop_name", "variety_name", "crop_start_date", "crop_start_type",
              "crop_end_date", "crop_end_type", "max_duration"}
    if not isinstance(calendar, dict) or set(calendar) != fields:
        raise ValueError("Agromanagement requires the exact CropCalendar fields")
    if any(not isinstance(calendar[key], str) or not calendar[key].strip()
           for key in ("crop_name", "variety_name")):
        raise ValueError("Agromanagement crop and variety names must be nonempty strings")
    start, end = calendar["crop_start_date"], calendar["crop_end_date"]
    if type(start) is not dt.date or start < campaign_start:
        raise ValueError("Crop start must be a native YAML date on or after campaign start")
    if calendar["crop_start_type"] not in {"sowing", "emergence"}:
        raise ValueError("Unsupported PCSE crop start type")
    if calendar["crop_end_type"] not in {"maturity", "harvest", "earliest"}:
        raise ValueError("Unsupported PCSE crop end type")
    if ((end is None and calendar["crop_end_type"] != "maturity")
            or (end is not None and (type(end) is not dt.date or end <= start))):
        raise ValueError("Agromanagement crop end date is absent or invalid for its end type")
    duration = calendar["max_duration"]
    if type(duration) is not int or duration <= 0:
        raise ValueError("Agromanagement max_duration must be a positive integer")
    duration_end = start + dt.timedelta(days=duration)
    return {"campaign_count": 1, "campaign_start": campaign_start.isoformat(),
            "crop_name": calendar["crop_name"], "variety_name": calendar["variety_name"],
            "crop_start_date": start.isoformat(), "crop_end_type": calendar["crop_end_type"],
            "crop_end_date": end.isoformat() if end else None, "max_duration": duration,
            "duration_limit_date": duration_end.isoformat(), "events_present": False,
            "implicit_selection": False}


def validate_output(path: Path, contract: dict) -> dict:
    """Return a format result for one file; caller enforces its project path."""
    report = {"ok": False, "policy": POLICY, "policy_sha256": source_digest(),
              "scientific_validation": "not_performed", "model_ready": False}
    try:
        _contract(contract)
        report.update({key: contract[key] for key in ("output_id", "path", "format")})
        weather = contract["format"] == "pcse_weather_csv_v1"
        raw, text = _read(Path(path), MAX_WEATHER_BYTES if weather else MAX_YAML_BYTES)
        report.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        facts = _weather(text) if weather else _agro(text, contract["campaign_start"])
        report.update(ok=True, facts=facts,
                      detail="Explicit format structure verified; scientific checks and model execution remain separate")
    except (OSError, ValueError, TypeError, UnicodeError, SyntaxError, csv.Error,
            yaml.YAMLError, OverflowError, RecursionError) as exc:
        report["detail"] = str(exc)[:600]
    return report
