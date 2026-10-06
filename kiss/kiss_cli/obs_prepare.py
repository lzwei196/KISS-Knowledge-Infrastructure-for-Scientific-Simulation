"""Read-only KI preparation estimates, separate from raw subset acquisition.

An estimate is a server plan, not permission to run a job or proof that inputs
exist. This module deliberately has no job, download, or raw-fallback operation.
Response fixtures are provisional until an authenticated server replay confirms
the deployed ``ki_prepare/1`` contract.
"""
from __future__ import annotations

from datetime import date
import json
import math
from pathlib import Path
import re
import time
import uuid

from . import data_contract
from . import obs_access as obs


REQUEST_FIELDS = frozenset({
    "model", "ki_step", "ki_version", "source", "mode", "lat", "lon", "bbox",
    "grid_res", "start", "end", "utc_offset",
})
CONTRACT_VERSION = "ki_prepare/1"
RESULT_SCHEMA = "geoforge.prepare-estimate.v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,120}\Z")
_PRIVATE_TEXT = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|www\.|\bBearer\s+|"
    r"\b(?:token|password|secret|authorization|api[_-]?key)\b|"
    r"(?:^|[\s\"'=:(\[])(?:[A-Za-z]:[\\/]|\\\\|/[A-Za-z0-9_.-]))",
    re.IGNORECASE,
)
_REDACTED = "[private server detail omitted]"


def _identifier(value, field):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must be a short explicit identifier")
    return value


def _number(value, field, low, high, *, positive=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not low <= value <= high or (positive and value <= 0)):
        raise ValueError(f"{field} is outside its valid numeric range")
    return float(value)


def request_body(body):
    """Validate an explicit plan request without using server source/mode defaults."""
    if not isinstance(body, dict):
        raise ValueError("Preparation request must be an object")
    if set(body) - REQUEST_FIELDS:
        raise ValueError("Unsupported preparation request fields")
    result = {key: _identifier(body.get(key), key) for key in ("model", "source", "mode")}
    if result["model"] not in {"shaw", "crhm", "vic"}:
        raise ValueError("This preparation client supports shaw, crhm and vic")
    for key in ("ki_step", "ki_version"):
        if body.get(key) is not None:
            result[key] = _identifier(body[key], key)
    for key in ("start", "end"):
        value = body.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"{key} must be an explicit YYYY-MM-DD date")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{key} must be a valid calendar date") from None
        result[key] = value
    if result["start"] > result["end"]:
        raise ValueError("Preparation start must not follow end")
    if result["model"] == "vic":
        if body.get("lat") is not None or body.get("lon") is not None:
            raise ValueError("VIC preparation needs a grid, not site coordinates")
        box = body.get("bbox")
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("VIC preparation requires bbox [west,south,east,north]")
        result["bbox"] = [_number(value, "bbox", -180 if i % 2 == 0 else -90,
                                  180 if i % 2 == 0 else 90)
                          for i, value in enumerate(box)]
        west, south, east, north = result["bbox"]
        if west >= east or south >= north:
            raise ValueError("Invalid bbox order; crossing the antimeridian needs separate requests")
        result["grid_res"] = _number(body.get("grid_res"), "grid_res", 0, 180, positive=True)
    else:
        if body.get("bbox") is not None or body.get("grid_res") is not None:
            raise ValueError("SHAW and CRHM preparation require site coordinates, not a grid")
        result["lat"] = _number(body.get("lat"), "lat", -90, 90)
        result["lon"] = _number(body.get("lon"), "lon", -180, 180)
    if body.get("utc_offset") is not None:
        value = body["utc_offset"]
        if type(value) is not int or not -12 <= value <= 14:
            raise ValueError("utc_offset must be an integer hour offset between -12 and 14")
        result["utc_offset"] = value
    return result


def _text(value, *, limit=600):
    if not isinstance(value, str) or len(value) > 8000:
        raise ValueError("Invalid public estimate text")
    if _PRIVATE_TEXT.search(value):
        return _REDACTED
    return " ".join(value.split())[:limit]


def _strings(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("Invalid public estimate list")
    return [_text(item) for item in value]


def _units(value):
    if isinstance(value, str):
        return _text(value, limit=160)
    if not isinstance(value, dict) or len(value) > 100:
        raise ValueError("Invalid estimate units")
    if any(not isinstance(key, str) for key in value):
        raise ValueError("Invalid estimate unit variable")
    return {_identifier(key, "variable"): _text(unit, limit=160)
            for key, unit in value.items()
            if not any(word in key.lower() for word in ("token", "secret", "password", "path", "url"))}


def _description(value):
    """Copy known public output/transform fields only, including nested structures."""
    if isinstance(value, str):
        return _text(value)
    if not isinstance(value, dict):
        raise ValueError("Invalid estimate output or transformation")
    result = {}
    for key in ("name", "role", "format", "description", "operation", "method", "from", "to",
                "source_cadence", "output_cadence", "cadence", "calendar", "timezone"):
        if key in value:
            result[key] = _text(value[key])
    for key in ("units", "input_units", "output_units"):
        if key in value:
            result[key] = _units(value[key])
    for key in ("columns", "variables"):
        if key in value:
            result[key] = (_text(value[key]) if isinstance(value[key], str)
                           else _strings(value[key]))
    for key in ("timestep_seconds", "interval_hours", "records", "estimated_bytes"):
        if key in value:
            result[key] = _number(value[key], key, 0, 10**16)
    return result


def _descriptions(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("Invalid estimate description list")
    return [_description(item) for item in value]


def _blockers(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("Invalid preparation blockers")
    result = []
    for item in value:
        if isinstance(item, str):
            result.append(_text(item) or "server_reported_blocker")
        elif isinstance(item, dict):
            # Preserve a useful code/message, never arbitrary backend diagnostic fields.
            code = item.get("code")
            message = item.get("message")
            if code is not None:
                code = _identifier(code, "blocker code")
            if message is not None:
                message = _text(message)
            result.append(": ".join(part for part in (code, message) if part)
                          or "server_reported_blocker")
        else:
            raise ValueError("Invalid preparation blocker")
    return result


def _check_echo(request, raw):
    """Any supplied request identity must agree; absent echoes prove nothing."""
    echoes = [raw]
    if "request" in raw:
        if not isinstance(raw["request"], dict):
            raise ValueError("Invalid echoed request")
        echoes.append(raw["request"])
    for echo in echoes:
        for key, wanted in request.items():
            if key not in echo:
                continue
            actual = echo[key]
            if key in ("lat", "lon", "grid_res"):
                same = type(actual) in (int, float) and math.isfinite(actual) and actual == wanted
            elif key == "bbox":
                same = (isinstance(actual, list) and len(actual) == 4
                        and all(type(v) in (int, float) and math.isfinite(v) for v in actual)
                        and actual == wanted)
            else:
                same = type(actual) is type(wanted) and actual == wanted
            if not same:
                raise ValueError("Server estimate identity differs from the request")


def _server_summary(request, raw):
    if not isinstance(raw, dict) or type(raw.get("preparable")) is not bool:
        raise ValueError("Invalid preparation estimate")
    _check_echo(request, raw)
    result = {"preparable": raw["preparable"]}
    for key in ("contract_version", "schema_version", "model", "ki_step", "ki_version", "source", "mode",
                "source_version", "processing_version", "processor_version"):
        if key in raw:
            result[key] = _text(raw[key], limit=160)
    for key in ("tool_hash", "shared_loader_hash", "source_version_hash", "contract_hash"):
        if key in raw:
            if not isinstance(raw[key], str) or not re.fullmatch(r"[a-fA-F0-9]{8,64}", raw[key]):
                raise ValueError("Invalid estimate version hash")
            result[key] = raw[key].lower()
    for key in ("source_cadence", "output_cadence"):
        if key in raw:
            result[key] = (_text(raw[key]) if isinstance(raw[key], str)
                           else _description(raw[key]))
    for key in ("transforms", "outputs"):
        if key in raw:
            result[key] = _descriptions(raw[key])
    for key in ("reason", "delivery_fallback"):
        if key in raw:
            result[key] = _description(raw[key])
    if "warnings" in raw:
        result["warnings"] = _strings(raw["warnings"])
    result["blockers"] = _blockers(raw.get("blockers", []))
    for key in ("estimated_output_bytes", "n_parts"):
        if key in raw:
            if type(raw[key]) is not int or raw[key] < 0:
                raise ValueError("Invalid estimate size/count")
            result[key] = raw[key]
    return result


def _result(request):
    return {
        "schema_version": RESULT_SCHEMA, "kind": "prepare_estimate", "delivery": "prepared",
        "request": request, "request_sha256": data_contract.fingerprint(request),
        "server_estimate": {}, "status": "estimate_failed", "plan_available": False,
        "blockers": [], "acquisition_approved": False, "input_ready": False, "model_ready": False,
        "note": "Exploratory estimate only. No job or download was started; inputs and model run remain unverified.",
    }


def _classify(result, summary):
    """Derive display status from sanitized evidence, including on local reread."""
    result["server_estimate"] = summary
    versions = [summary[key] for key in ("contract_version", "schema_version") if key in summary]
    blockers = list(summary["blockers"])
    if not versions or any(version != CONTRACT_VERSION for version in versions):
        result.update(status="unsupported_contract", plan_available=False,
                      blockers=list(dict.fromkeys(blockers + ["unrecognized_preparation_contract"])))
        return result
    if not summary["preparable"]:
        blockers.append("preparation_not_supported")
    if not blockers and (not summary.get("source_cadence") or not summary.get("outputs")
                         or any(not output for output in summary.get("outputs", []))):
        blockers.append("incomplete_preparation_plan")
    result.update(status="blocked" if blockers else "estimate_available",
                  blockers=list(dict.fromkeys(blockers)), plan_available=not blockers)
    return result


def _failure(result, code, status=None):
    if code not in obs.ERROR_MESSAGES and code != "invalid_response":
        code = "request_failed"
    result["failure"] = {"stage": "estimate", "code": code}
    if type(status) is int and 100 <= status < 600:
        result["failure"]["http_status"] = status
    result["message"] = obs.ERROR_MESSAGES.get(code, "The server did not provide a supported preparation estimate.")
    result["blockers"] = ["estimate_unavailable"]
    return result


def estimate(body, *, client=None):
    """Obtain one read-only server plan; safe for CLI and project agent callers."""
    request = request_body(body)
    result = _result(request)
    try:
        raw = (client or obs.Client())._json("/prepare/estimate", method="POST", body=request)
        summary = _server_summary(request, raw)
    except (obs.ObsAccessError, ValueError, TypeError, OSError) as error:
        code = error.code if isinstance(error, obs.ObsAccessError) else "invalid_response"
        return _failure(result, code, getattr(error, "status", None))
    return _classify(result, summary)


def _root(project):
    project = Path(project).resolve()
    root = project / ".geoforge" / "preparations"
    if not root.resolve().is_relative_to(project):
        raise ValueError("Preparation evidence directory escapes the project")
    return root


def record_estimate(project, body, *, client=None):
    """Persist only sanitized exploratory evidence, never an acquisition receipt."""
    root = _root(project)
    result = estimate(body, client=client)
    result.update(preparation_id=uuid.uuid4().hex, created_at=time.time())
    root.mkdir(parents=True, exist_ok=True)
    obs._atomic_json(root / (result["preparation_id"] + ".json"), result)
    return result


def list_estimates(project):
    """Read safe local summaries; files are data, not trusted approval state."""
    root = _root(project)
    if not root.exists():
        return []
    results = []
    for path in root.glob("*.json"):
        if not re.fullmatch(r"[a-f0-9]{32}", path.stem) or path.is_symlink():
            continue
        try:
            if path.stat().st_size > 256 * 1024:
                continue
            saved = json.loads(path.read_text(encoding="utf-8"))
            request = request_body(saved["request"])
            clean = _result(request)
            if saved.get("request_sha256") != clean["request_sha256"]:
                continue
            summary = saved.get("server_estimate") or {}
            if summary:
                _classify(clean, _server_summary(request, summary))
            elif saved.get("status") == "estimate_failed":
                failure = saved.get("failure")
                if not isinstance(failure, dict):
                    continue
                _failure(clean, failure.get("code"), failure.get("http_status"))
            else:
                continue
            clean["preparation_id"] = path.stem
            clean["created_at"] = _number(saved.get("created_at"), "created_at", 0, 10**12)
            results.append(clean)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return sorted(results, key=lambda item: item["created_at"], reverse=True)
