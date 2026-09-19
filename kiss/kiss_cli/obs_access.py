"""Authenticated GeoForge Database catalogue and verified downloads."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import secret_store, settings, tls
from .firstrun import data_dir

BASE_URL = "https://app.geoforgehhu.com/api/obs"
TOKEN_SERVICE = "com.geoforge.desktop"
TOKEN_ACCOUNT = "observation-activation-token"
PROXY_TARGET = "network:obs"
MAX_SERVED_BYTES = 100 * 1024 * 1024   # the service serves files up to 100 MB; larger ones are manual
CATALOGUE_PAGE_SIZE = 500          # the service accepts limit <= 500
CATALOGUE_SNAPSHOT_SCHEMA = "geoforge.database.catalogue.v1"
CATALOGUE_SNAPSHOT = Path(".geoforge/database/catalogue.json")
CATALOGUE_CACHE_SECONDS = 15 * 60
# One app-level copy of the catalogue (metadata only, ~1,100 records).  Every
# search surface (data panel, API tool, CLI command) filters this copy locally;
# the server is contacted only to refresh it.
CATALOGUE_STORE_TTL = 6 * 3600
_STORE_LOCK = threading.RLock()
# Held only by the one thread doing network/credential work for a refresh.
# Everyone else keeps using the current copy: a refresh that is waiting on a
# Keychain consent dialog must never stall searches or unrelated routes.
_REFRESH_LOCK = threading.Lock()

# Reading a generic password from macOS Keychain can display a native consent
# dialog.  Catalogue searches are deliberately cheap and Agents commonly issue
# several of them in one turn, so looking the same credential up per HTTP
# request produces one dialog per query.  Keep the credential in this Desktop
# process after the first lookup.  It never crosses the Agent boundary and is
# replaced immediately when Settings changes it.
_TOKEN_NOT_LOADED = object()
_token_cache: str | None | object = _TOKEN_NOT_LOADED
_token_error_cache: ObsAccessError | None = None
_TOKEN_LOCK = threading.RLock()

# Only catalogue metadata crosses the Agent boundary.  Authentication material,
# signed delivery URLs and Baidu extraction details remain inside GeoForge and
# are revealed to the user (not the Agent) only after an approved download.
CATALOGUE_PUBLIC_FIELDS = frozenset({
    "id", "dataset_id", "name", "title", "description", "summary",
    "dataset_kind", "type", "variables", "variable", "units", "unit",
    "domain", "domains", "applicable_domains", "tags", "keywords", "source", "provider",
    "license", "citation", "format", "delivery", "availability", "status",
    "size", "size_bytes", "resolution", "spatial_resolution",
    "temporal_resolution", "spatial_extent", "spatial_coverage", "bbox",
    "geometry", "region", "regions", "country", "basin", "station",
    "station_id", "gauge_id", "latitude", "longitude", "lat", "lon",
    "temporal_extent", "period", "start", "end", "start_date", "end_date",
    "time_start", "time_end", "calendar", "crs", "version", "updated_at",
    # 2026-09-11 serializer fields plus prose notes (coverage often lives there)
    "notes", "shape", "n_records", "sha256", "bbox", "point", "temporal",
    "resolution_deg", "parent_id", "aliases", "category", "time_step",
    "region_names", "canonical",
})
CATALOGUE_PRIVATE_FIELD_PARTS = (
    "token", "secret", "password", "passwd", "pwd", "cookie",
    "authorization", "signed_url", "download_url", "baidu_url", "href",
    "uri", "link", "credential", "access_key", "extraction_code",
)

ERROR_MESSAGES = {
    "missing_token": "Paste your activation token in Settings.",
    "invalid_token": "That token isn't right — check for a copy/paste miss.",
    "expired_token": "Your token expired — ask the group owner for a new one.",
    "revoked_token": "This token was revoked — ask the group owner.",
    "quota_exceeded": "Daily download limit reached; resets at midnight server time.",
    "network_error": "GeoForge could not reach GeoForge Database.",
    "checksum_mismatch": "The downloaded file failed integrity verification twice.",
    "unsafe_archive": "The downloaded archive contains an unsafe path.",
    "secret_store_unavailable": "The system password store is unavailable on this machine.",
    "server_unavailable": "GeoForge Database server or gateway is unavailable.",
    "unknown_variable": (
        "The server rejected an unknown source variable. Read the dataset schema with "
        "describe_dataset_id (CLI: --describe DATASET_ID), then submit a revised estimate "
        "using exact source names. Do not remove the variable filter to bypass this error."
    ),
    "variable_selection_unsupported": (
        "This dataset is delivered whole (raster bands/layers are not selectable). Read the "
        "schema with describe_dataset_id (CLI: --describe DATASET_ID), then re-estimate with an "
        "empty variable list to request the whole file for the bbox."
    ),
}

DATA_DISCOVERY_RULES = (
    "After catalogue discovery, inspect each candidate's live source schema using "
    "describe_dataset (API) or the provided Desktop database "
    "command with --describe DATASET_ID. Catalogue variable labels can differ from "
    "source names. Choose exact returned names using their descriptions, units and "
    "dimensions; never guess a translation. If the meaning is ambiguous, ask rather "
    "than choosing silently. Describe reads metadata only: it proves neither valid "
    "data values nor delivery for the requested area/period. Inspect files/schemas "
    "and their notes: shared variable names do not imply a single crop/member, and "
    "raster bands may be informational rather than selectable. Do not invent a "
    "member/band selector. An empty variables list explicitly requests all fields; "
    "never use it to bypass an unknown-variable error.\n"
    "Catalogue discovery is not live delivery verification (API: search_catalogue, then "
    "describe_dataset, then estimate_clip). A matching record (even "
    "from a fresh catalogue) does not prove that server clipping works now. Before "
    "offering a server-subset download for approval, obtain a read-only subset estimate "
    "for the exact dataset, bbox, dates and native variables. Quote output bytes, part "
    "counts and clipped coverage only when returned by that estimate; otherwise label "
    "them unknown, not verified. An estimate is allowed before download approval and "
    "does not authorize a job. If it fails, report the recorded failure and stop that "
    "acquisition; do not convert an outage into a manual-download requirement. Separate "
    "missing metadata, temporarily unavailable delivery, unsupported clipping and "
    "missing scientific inputs. Dataset units/fields remain metadata claims until "
    "the actual files and the KI input requirements have been checked.\n"
    "A clip estimate is exploration; the plan is the proposal. Put each chosen clip on its "
    "data-inventory item in write_plan (dataset_id plus the study bbox/period/variables in "
    "requirements, or the estimate's acquisition_id). GeoForge joins the item to the matching "
    "estimate, re-estimates it before the card, and starts the server job when the user approves "
    "the plan. There is no separate data approval. State inspection-only or all-member scope in "
    "the item's notes.\n"
    "Search each required data category separately. This is lexical catalogue search, "
    "not semantic question answering: all query words must match. Use bbox for location "
    "and separate date/variable filters; national/global products need not name the town. "
    "A sparse or irrelevant result from one query does not establish missing data. "
    "Before asking the user to supply data, search the candidate source/product names "
    "explicitly mentioned by the KI, one at a time, then check their native variables "
    "and coverage. If they still do not match, report the searches and leave availability "
    "unknown rather than declaring that the entire database has no such data.\n"
)


class ObsAccessError(RuntimeError):
    def __init__(self, code: str, message: str | None = None,
                 *, status: int | None = None):
        self.code = code
        self.status = status
        super().__init__(message or ERROR_MESSAGES.get(code) or
                         "Observation data request failed.")

    def payload(self) -> dict:
        return {"ok": False, "error": self.code, "message": str(self),
                **({"http_status": self.status} if self.status is not None else {})}


def _secret_error(error: Exception) -> ObsAccessError:
    return ObsAccessError("secret_store_unavailable", str(error))


def token() -> str | None:
    global _token_cache, _token_error_cache
    with _TOKEN_LOCK:
        if _token_error_cache is not None:
            raise ObsAccessError(
                _token_error_cache.code, str(_token_error_cache),
                status=_token_error_cache.status)
        if _token_cache is not _TOKEN_NOT_LOADED:
            return _token_cache  # type: ignore[return-value]
        try:
            loaded = secret_store.get_secret(TOKEN_SERVICE, TOKEN_ACCOUNT)
        except (secret_store.SecretStoreUnavailable,
                secret_store.SecretStoreError) as error:
            # A denied/cancelled macOS Keychain request must not be retried by
            # every catalogue query in the same Agent turn.  Keep the failure
            # for this Desktop process; the explicit Settings test clears it.
            cached = _secret_error(error)
            _token_error_cache = cached
            raise cached from error
        _token_cache = loaded
        _token_error_cache = None
        return loaded


def token_configured() -> bool:
    return bool(token())


def token_state() -> str:
    """Non-blocking view of the credential: never opens a Keychain prompt.

    'configured' / 'missing' once the token was read in this process,
    'error' when that read failed, 'pending' while another thread is inside
    the native password store (a consent dialog may be open), 'unknown' when
    nothing has asked for it yet.
    """
    if not _TOKEN_LOCK.acquire(blocking=False):
        return "pending"
    try:
        if _token_error_cache is not None:
            return "error"
        if _token_cache is _TOKEN_NOT_LOADED:
            return "unknown"
        return "configured" if _token_cache else "missing"
    finally:
        _TOKEN_LOCK.release()


def set_token(value: str) -> None:
    global _token_cache, _token_error_cache
    clean = str(value or "").strip()
    with _TOKEN_LOCK:
        try:
            if clean:
                secret_store.set_secret(TOKEN_SERVICE, TOKEN_ACCOUNT, clean)
            else:
                secret_store.delete_secret(TOKEN_SERVICE, TOKEN_ACCOUNT)
        except (secret_store.SecretStoreUnavailable,
                secret_store.SecretStoreError) as error:
            raise _secret_error(error) from error
        _token_cache = clean or None
        _token_error_cache = None


def retry_token_access() -> None:
    """Allow one explicit Settings action to retry native credential access."""
    global _token_cache, _token_error_cache
    with _TOKEN_LOCK:
        _token_cache = _TOKEN_NOT_LOADED
        _token_error_cache = None


def _safe_filename(value: str, fallback: str) -> str:
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", value or "",
                      flags=re.IGNORECASE)
    candidate = urllib.parse.unquote(match.group(1)).strip() if match else fallback
    candidate = Path(candidate).name
    return candidate if candidate not in {"", ".", ".."} else fallback


def _safe_component(value: str, fallback: str = "dataset") -> str:
    """Turn an opaque server identifier into one local path component."""
    component = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._")
    return component[:120] or fallback


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _below_inputs(project: Path, requested: str | None, dataset_id: str) -> Path:
    root = (project.resolve() / "inputs").resolve()
    relative = requested or f"observations/{dataset_id}"
    raw = Path(relative)
    target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ObsAccessError(
            "invalid_destination",
            "Observation data must be saved inside this project's inputs folder.") from error
    return target


def _extract_zip(archive: Path, target: Path) -> list[Path]:
    if target.exists() and any(target.iterdir() if target.is_dir() else [target]):
        raise ObsAccessError(
            "destination_exists",
            f"The dataset destination already contains files: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                member = PurePosixPath(info.filename)
                mode = info.external_attr >> 16
                if (member.is_absolute() or ".." in member.parts or
                        stat.S_ISLNK(mode)):
                    raise ObsAccessError("unsafe_archive")
                candidate = stage.joinpath(*member.parts).resolve()
                try:
                    candidate.relative_to(stage.resolve())
                except ValueError as error:
                    raise ObsAccessError("unsafe_archive") from error
                bundle.extract(info, stage)
        if target.exists():
            target.rmdir()
        os.replace(stage, target)
        return [path for path in target.rglob("*") if path.is_file()]
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


class Client:
    """Client whose responses never expose the bearer token."""

    def __init__(self, *, opener=None, token_getter=token,
                 base_url: str = BASE_URL, timeout: int = 90):
        self._provided_opener = opener
        self._token_getter = token_getter
        self.base_url = base_url.rstrip("/")
        self.timeout = max(1, int(timeout))

    def _opener(self):
        if self._provided_opener is not None:
            return self._provided_opener
        proxy = settings.proxy_url_for(PROXY_TARGET)
        proxy_handler = urllib.request.ProxyHandler(
            {"http": proxy, "https": proxy} if proxy else {})
        return urllib.request.build_opener(
            proxy_handler, urllib.request.HTTPSHandler(context=tls.context()))

    def _request(self, path: str, *, method: str = "GET", body=None):
        bearer = self._token_getter()
        if not bearer:
            raise ObsAccessError("missing_token")
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body, allow_nan=False).encode() if body is not None else None,
            method=method,
            headers={"Authorization": f"Bearer {bearer}",
                     "Content-Type": "application/json",
                     "Accept": "application/json, application/octet-stream",
                     "User-Agent": "GeoForge-Desktop/obs-v1"})
        try:
            return self._opener().open(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            if 500 <= error.code < 600:
                raise ObsAccessError(
                    "server_unavailable",
                    f"GeoForge Database server or gateway returned HTTP {error.code}. "
                    "Live delivery is unverified; a cached catalogue is not a successful estimate.",
                    status=error.code) from error
            try:
                body = json.loads(error.read().decode("utf-8", "replace"))
                detail = body.get("detail") if isinstance(body, dict) else None
                code = detail.get("error") if isinstance(detail, dict) else None
            except (ValueError, OSError):
                code = None
            code = code or ("quota_exceeded" if error.code == 429 else
                            "request_failed")
            raise ObsAccessError(code, status=error.code) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ObsAccessError("network_error", f"{ERROR_MESSAGES['network_error']} {error}") from error

    def _json(self, path: str, *, method: str = "GET", body=None) -> dict:
        with self._request(path, method=method, body=body) as response:
            try:
                return json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ObsAccessError(
                    "invalid_response", "The observation service returned invalid JSON.") from error

    def test(self) -> dict:
        result = self.catalogue(limit=1)
        return {"ok": True, "configured": True,
                "total": int(result.get("total") or 0)}

    def catalogue(self, *, q: str = "", offset: int = 0,
                  limit: int = 25) -> dict:
        query = urllib.parse.urlencode({
            "offset": max(0, int(offset)),
            "limit": min(CATALOGUE_PAGE_SIZE, max(1, int(limit))),
            "q": str(q or "")[:300],
        })
        return self._json(f"/catalogue?{query}")

    def dataset(self, dataset_id: str) -> dict:
        safe_id = urllib.parse.quote(str(dataset_id), safe="")
        return self._json(f"/{safe_id}")

    def describe(self, dataset_id: str) -> dict:
        if not isinstance(dataset_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,180}", dataset_id):
            raise ValueError("Invalid catalogue dataset id")
        return self._json("/subsets/describe?" + urllib.parse.urlencode({"dataset_id": dataset_id}))

    def resolve(self, dataset_id: str, *, bbox=None, start=None, end=None,
                variable: str = "", time_step: str = "") -> dict:
        params = {"dataset_id": dataset_id, "variable": variable,
                  "start": start or "", "end": end or "", "time_step": time_step}
        if bbox:
            box = _bbox(bbox)
            if box is None:
                raise ValueError("invalid bbox")
            params["bbox"] = ",".join(str(v) for v in box)
        # Reuse filter validation even when the catalogue is empty.
        local_search([], bbox=bbox, start=start, end=end)
        if time_step not in ("", "daily", "3hr"):
            raise ValueError("time_step must be daily or 3hr")
        return self._json("/resolve?" + urllib.parse.urlencode({k: v for k, v in params.items() if v}))

    def download(self, dataset_id: str, project: Path, *,
                 destination: str | None = None) -> dict:
        dataset_id = str(dataset_id).strip()
        if not dataset_id:
            raise ObsAccessError("invalid_dataset", "A dataset id is required.")
        target = _below_inputs(project, destination, dataset_id)
        if target.is_dir() and any(p for p in target.rglob("*") if p.is_file() and not p.name.startswith(".")):
            # Decide before downloading: an existing delivery is evidence, and the
            # archive under .geoforge/downloads must never be overwritten or deleted
            # by a second attempt (2026-09-18: a retry destroyed two receipts' raw zips).
            raise ObsAccessError(
                "destination_not_empty",
                f"The dataset destination already contains files: {target}")
        safe_id = urllib.parse.quote(dataset_id, safe="")
        local_id = _safe_component(dataset_id)
        temp_root = project.resolve() / ".geoforge" / "tmp" / "observations"
        temp_root.mkdir(parents=True, exist_ok=True)

        for attempt in range(2):
            raw_temp: Path | None = None
            try:
                route = (f"/child/{safe_id}/download" if CHILD_ID.match(dataset_id)
                         else f"/{safe_id}/download")
                with self._request(route) as response:
                    content_type = (response.headers.get("Content-Type") or "").lower()
                    if "json" in content_type:
                        payload = json.loads(response.read().decode("utf-8"))
                        if payload.get("served") is False:
                            return {**payload, "ok": True, "served": False,
                                    "dataset_id": dataset_id,
                                    "destination": str(target)}
                        raise ObsAccessError("invalid_response")

                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > MAX_SERVED_BYTES:
                        raise ObsAccessError(
                            "response_too_large",
                            "The server offered a file larger than the desktop download limit.")
                    name = _safe_filename(
                        response.headers.get("Content-Disposition") or "",
                        f"{dataset_id}.bin")
                    expected = (response.headers.get("X-Content-SHA256") or "").lower()
                    fd, raw_name = tempfile.mkstemp(
                        prefix=f".{local_id}-", suffix=".part", dir=temp_root)
                    raw_temp = Path(raw_name)
                    received = 0
                    digest = hashlib.sha256()
                    with os.fdopen(fd, "wb") as stream:
                        for chunk in iter(lambda: response.read(1024 * 1024), b""):
                            received += len(chunk)
                            if received > MAX_SERVED_BYTES:
                                raise ObsAccessError("response_too_large")
                            digest.update(chunk)
                            stream.write(chunk)
                        stream.flush()
                        os.fsync(stream.fileno())
                    actual = digest.hexdigest()
                    if not expected or actual != expected:
                        raw_temp.unlink(missing_ok=True)
                        if attempt == 0:
                            continue
                        raise ObsAccessError("checksum_mismatch")

                    is_zip = name.lower().endswith(".zip") or zipfile.is_zipfile(raw_temp)
                    if is_zip:
                        evidence_dir = (project.resolve() / ".geoforge" /
                                        "downloads" / local_id)
                        evidence_dir.mkdir(parents=True, exist_ok=True)
                        archive = evidence_dir / name
                        os.replace(raw_temp, archive)
                        raw_temp = None
                        try:
                            files = _extract_zip(archive, target)
                        except Exception:
                            archive.unlink(missing_ok=True)
                            raise
                        return {"ok": True, "served": True,
                                "dataset_id": dataset_id,
                                "destination": str(target),
                                "raw_file": str(archive),
                                "files": [str(path) for path in files],
                                "sha256": actual, "size": received}

                    final = target / name if not target.suffix else target
                    final.parent.mkdir(parents=True, exist_ok=True)
                    if final.exists():
                        if _hash(final) == actual:
                            raw_temp.unlink(missing_ok=True)
                            return {"ok": True, "served": True,
                                    "dataset_id": dataset_id,
                                    "destination": str(final),
                                    "raw_file": str(final), "files": [str(final)],
                                    "sha256": actual, "size": received,
                                    "reused": True}
                        raise ObsAccessError(
                            "destination_exists",
                            f"A different file already exists at {final}")
                    os.replace(raw_temp, final)
                    raw_temp = None
                    return {"ok": True, "served": True,
                            "dataset_id": dataset_id,
                            "destination": str(final), "raw_file": str(final),
                            "files": [str(final)], "sha256": actual,
                            "size": received}
            except ObsAccessError as error:
                if error.code == "network_error" and attempt == 0:
                    continue
                raise
            except (http.client.HTTPException, urllib.error.URLError,
                    TimeoutError, OSError) as error:
                if attempt == 0:
                    continue
                raise ObsAccessError("network_error") from error
            finally:
                if raw_temp is not None:
                    raw_temp.unlink(missing_ok=True)
        raise ObsAccessError("checksum_mismatch")


def _public_value(value, *, depth: int = 0):
    """Bound and copy JSON catalogue values without retaining opaque objects."""
    if depth > 5:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:8000]
    if isinstance(value, list):
        return [_public_value(item, depth=depth + 1) for item in value[:500]]
    if isinstance(value, dict):
        return {
            str(key)[:120]: _public_value(item, depth=depth + 1)
            for key, item in list(value.items())[:200]
            if not any(secret in str(key).lower()
                       for secret in CATALOGUE_PRIVATE_FIELD_PARTS)
        }
    return str(value)[:1000]


def public_dataset(record: dict) -> dict:
    """Return the metadata an Agent may inspect; never delivery credentials."""
    if not isinstance(record, dict):
        return {}
    public = {
        key: _public_value(value)
        for key, value in record.items()
        if str(key) in CATALOGUE_PUBLIC_FIELDS
    }
    if "id" not in public and public.get("dataset_id"):
        public["id"] = public["dataset_id"]
    return public if str(public.get("id") or "").strip() else {}


def public_catalogue(payload: dict) -> dict:
    """Normalize one server page into the app-wide public catalogue contract."""
    if not isinstance(payload, dict):
        raise ObsAccessError("invalid_response", "The database catalogue was not a JSON object.")
    raw = payload.get("datasets")
    if raw is None:
        raw = payload.get("items")
    if not isinstance(raw, list):
        raise ObsAccessError("invalid_response", "The database catalogue has no dataset list.")
    datasets = [item for item in (public_dataset(record) for record in raw) if item]
    result = {
        "ok": True,
        "service": "GeoForge Database",
        "total": int(payload.get("total") or len(datasets)),
        "datasets": datasets,
    }
    for key in ("offset", "limit", "query", "q"):
        if key in payload:
            result[key] = _public_value(payload[key])
    return result


def _server_search(*, q: str = "", offset: int = 0, limit: int = 25,
                   client: Client | None = None) -> dict:
    backend = client or Client()
    raw = backend.catalogue(q=q, offset=offset, limit=limit)
    result = public_catalogue(raw)
    if isinstance(raw, dict) and raw.get("etag"):
        result["etag"] = str(raw["etag"])[:200]
    return result


def complete_catalogue(*, q: str = "", client: Client | None = None,
                       max_items: int = 20000) -> dict:
    """Page through the whole metadata catalogue (server side)."""
    backend = client or Client()
    datasets: list[dict] = []
    seen: set[str] = set()
    offset = 0
    total = 0
    etag = None
    while len(datasets) < max(1, int(max_items)):
        page = _server_search(q=q, offset=offset, limit=CATALOGUE_PAGE_SIZE, client=backend)
        etag = etag or page.get("etag")
        batch = page["datasets"]
        total = max(total, int(page.get("total") or 0))
        for record in batch:
            dataset_id = str(record.get("id") or "")
            if dataset_id and dataset_id not in seen:
                seen.add(dataset_id)
                datasets.append(record)
                if len(datasets) >= max_items:
                    break
        offset += len(batch)
        if not batch or offset >= total:
            break
    return {
        "ok": True,
        "service": "GeoForge Database",
        "etag": etag,
        "total": total or len(datasets),
        "returned": len(datasets),
        "truncated": len(datasets) < total,
        "datasets": datasets,
    }


# ---------------------------------------------------------------------------
# app-level catalogue store + local search
# ---------------------------------------------------------------------------

def catalogue_store_path() -> Path:
    return data_dir() / "database" / "catalogue.json"


def load_catalogue() -> dict | None:
    return _read_snapshot(catalogue_store_path())


def refresh_catalogue(*, client: Client | None = None, force: bool = False,
                      path: Path | None = None, ttl: int = CATALOGUE_STORE_TTL,
                      max_items: int = 20000) -> dict:
    """Return the catalogue payload at *path*, refreshing it from the server when due.

    A fresh copy is kept as long as ``ttl``; after that one cheap request compares
    the server ETag and a full re-page happens only when it changed.  When the
    server is unreachable the previous copy is kept and marked stale with the
    error, so a search can still answer and the Agent can report the outage.
    """
    path = Path(path) if path is not None else catalogue_store_path()
    previous = _read_snapshot(path)
    now = datetime.now(timezone.utc)
    if not force and previous:
        age = now.timestamp() - float(previous.get("generated_at_epoch") or 0)
        error_code = str((previous.get("error") or {}).get("code") or "")
        auth_error = error_code in {
            "missing_token", "invalid_token", "expired_token", "revoked_token"}
        budget = max(0, int(ttl)) if previous.get("ok") else (0 if auth_error else 60)
        if 0 <= age <= budget:
            return previous
    if not _REFRESH_LOCK.acquire(blocking=False):
        # A refresh is already under way, possibly waiting on the password store's
        # consent dialog.  Answer from the copy we have instead of joining the wait.
        if previous and previous.get("datasets"):
            return {**previous, "stale": True}
        return {"schema_version": CATALOGUE_SNAPSHOT_SCHEMA, "ok": False,
                "service": "GeoForge Database", "stale": False, "total": 0, "datasets": [],
                "generated_at": now.isoformat(), "generated_at_epoch": now.timestamp(),
                "error": {"code": "refreshing",
                          "message": "The catalogue is being fetched; try again in a moment."}}
    try:
        backend = client or Client()
        try:
            if (previous and previous.get("ok") and previous.get("etag") and
                    previous.get("datasets")):
                head = _server_search(q="", offset=0, limit=1, client=backend)
                if head.get("etag") == previous["etag"]:
                    payload = {**previous, "generated_at": now.isoformat(),
                               "generated_at_epoch": now.timestamp(), "stale": False}
                    payload.pop("error", None)
                    with _STORE_LOCK:
                        _atomic_json(path, payload)
                    return payload
            catalogue = complete_catalogue(client=backend, max_items=max_items)
            payload = {
                "schema_version": CATALOGUE_SNAPSHOT_SCHEMA,
                "generated_at": now.isoformat(),
                "generated_at_epoch": now.timestamp(),
                **catalogue,
            }
        except (ObsAccessError, TypeError, ValueError, OSError) as error:
            if isinstance(error, ObsAccessError):
                error_code, error_message = error.code, str(error)
            else:
                error_code = "invalid_response"
                error_message = "GeoForge Database returned catalogue metadata the app could not read."
            cached_raw = (previous or {}).get("datasets")
            cached = ([item for item in
                       (public_dataset(record) for record in cached_raw) if item]
                      if isinstance(cached_raw, list) else [])
            payload = {
                "schema_version": CATALOGUE_SNAPSHOT_SCHEMA,
                "generated_at": now.isoformat(),
                "generated_at_epoch": now.timestamp(),
                "ok": False,
                "service": "GeoForge Database",
                "etag": (previous or {}).get("etag"),
                "error": {"code": error_code, "message": error_message},
                "stale": bool(cached),
                "total": len(cached),
                "datasets": cached,
            }
        with _STORE_LOCK:
            _atomic_json(path, payload)
        return payload
    finally:
        _REFRESH_LOCK.release()


def _variable_names(record: dict) -> list[str]:
    names: list[str] = []
    for item in record.get("variables") or []:
        if isinstance(item, dict):
            names.extend(str(v) for v in (item.get("name"), item.get("canonical")) if v)
        elif item:
            names.append(str(item))
    return names


def variable_terms(value) -> list[str]:
    """One variable-list interpretation for search, assessment and requests.

    Accept legacy comma-separated strings and lists. Search may use each term
    as a discovery hint; assessment requires declared names/canonical aliases.
    """
    if value in (None, ""):
        return []
    values = value.split(",") if isinstance(value, str) else value
    if not isinstance(values, (list, tuple)) or any(not isinstance(v, str) for v in values):
        raise ValueError("variables must be a list of names or comma-separated names")
    return sorted({v.strip().casefold() for v in values if v.strip()})


def _bbox(value) -> tuple[float, float, float, float] | None:
    import math
    if isinstance(value, str):
        value = value.split(",")
    try:
        lon0, lat0, lon1, lat1 = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (lon0, lat0, lon1, lat1)):
        return None
    if not (-180 <= lon0 <= 180 and -180 <= lon1 <= 180 and -90 <= lat0 <= 90 and -90 <= lat1 <= 90):
        return None
    return (min(lon0, lon1), min(lat0, lat1), max(lon0, lon1), max(lat0, lat1))


def _point(record: dict) -> tuple[float, float] | None:
    raw = record.get("point")
    try:
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            return float(raw[0]), float(raw[1])
        if record.get("lat") not in (None, "") and record.get("lon") not in (None, ""):
            return float(record["lat"]), float(record["lon"])
    except (TypeError, ValueError):
        pass
    return None


def _iso(value, *, end: bool = False) -> str | None:
    import calendar
    import datetime
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}", text):
        return f"{text}-12-31" if end else f"{text}-01-01"
    if re.fullmatch(r"\d{4}-\d{2}", text):
        try:
            year, month = map(int, text.split("-"))
            day = calendar.monthrange(year, month)[1] if end else 1
            return datetime.date(year, month, day).isoformat()
        except ValueError:
            return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return datetime.date.fromisoformat(text).isoformat()
        except ValueError:
            return None
    return None


_BLOB_FIELDS = ("id", "name", "notes", "description", "spatial_coverage", "type",
                "dataset_kind", "category", "format", "applicable_domains",
                "region_names", "aliases", "parent_id", "resolution")


def _blob(record: dict) -> str:
    parts = [json.dumps(record.get(k), ensure_ascii=False) for k in _BLOB_FIELDS
             if record.get(k) not in (None, "", [], {})]
    parts.extend(_variable_names(record))
    return " ".join(parts).lower()


def assess_dataset(record: dict, *, bbox=None, start=None, end=None, variable="") -> dict:
    """Metadata suitability, never proof of file validity or spatial clipping."""
    checks = {}
    if bbox:
        box, own = _bbox(bbox), _bbox(record.get("bbox"))
        if box is None:
            raise ValueError("bbox must contain four finite WGS84 coordinates")
        checks["spatial"] = ("unknown" if own is None else
            "covered" if own[0] <= box[0] and own[1] <= box[1] and own[2] >= box[2] and own[3] >= box[3]
            else "insufficient")
    for key, requested, actual in (("start", start, record.get("start_date")),
                                    ("end", end, record.get("end_date"))):
        if requested:
            want, have = _iso(requested, end=key == "end"), _iso(actual, end=key == "end")
            if want is None:
                raise ValueError(f"invalid {key} date")
            checks[key] = ("unknown" if have is None else "covered" if
                           (have <= want if key == "start" else have >= want) else "insufficient")
    if variable:
        wanted = variable_terms(variable)
        names = {n.lower() for n in _variable_names(record)}
        checks["variables"] = ("unknown" if not names else
                               "covered" if all(v in names for v in wanted) else "unknown")
    status = ("insufficient" if "insufficient" in checks.values() else
              "unknown" if not checks or "unknown" in checks.values() else "covered")
    return {"status": status, "checks": checks,
            "delivery": record.get("delivery") or "unknown",
            "requires_local_extraction": bool(bbox and _bbox(record.get("bbox")) != _bbox(bbox)),
            "note": "Metadata coverage only; verify units, resolution and actual files before simulation."}


def local_search(records: list[dict], *, q: str = "", bbox=None, start=None, end=None,
                 variable: str = "", category: str = "", delivery: str = "",
                 offset: int = 0, limit: int = 25) -> dict:
    """Filter catalogue records locally.

    Words in ``q`` must all appear somewhere in the record.  A bbox excludes only
    records whose own geometry lies outside it; records without geometry are kept
    and ranked last so a basin shapefile with no bbox is still found by name.
    A period excludes only records whose dates do not overlap.
    """
    words = [w for w in str(q or "").lower().split() if w]
    box = _bbox(bbox) if bbox else None
    if bbox and box is None:
        raise ValueError("invalid bbox")
    start_iso = _iso(start) if start else None
    end_iso = _iso(end, end=True) if end else None
    if (start and start_iso is None) or (end and end_iso is None):
        raise ValueError("invalid date filter")
    if start_iso and end_iso and start_iso > end_iso:
        raise ValueError("start must not be after end")
    want_variables = variable_terms(variable)
    want_category = str(category or "").lower().strip()
    want_delivery = str(delivery or "").lower().strip()
    scored: list[tuple[int, str, dict]] = []
    for record in records:
        if not isinstance(record, dict) or not record.get("id"):
            continue
        blob = _blob(record)
        if words and not all(w in blob for w in words):
            continue
        if want_delivery and str(record.get("delivery") or "").lower() != want_delivery:
            continue
        if want_category and want_category not in {
                str(record.get(k) or "").lower() for k in ("dataset_kind", "type", "category")}:
            continue
        if want_variables and not all(any(v in n.casefold() for n in _variable_names(record))
                                      for v in want_variables):
            continue
        geometry = None
        if box:
            own = _bbox(record.get("bbox")) if record.get("bbox") else None
            pt = _point(record)
            if own:
                geometry = not (own[2] < box[0] or own[0] > box[2] or own[3] < box[1] or own[1] > box[3])
            elif pt:
                geometry = box[1] <= pt[0] <= box[3] and box[0] <= pt[1] <= box[2]
            if geometry is False:
                continue
        if start_iso or end_iso:
            rs, re_ = _iso(record.get("start_date")), _iso(record.get("end_date"), end=True)
            if rs and re_ and ((end_iso and rs > end_iso) or (start_iso and re_ < start_iso)):
                continue
        head = f"{record.get('id', '')} {record.get('name', '')}".lower()
        score = (0 if geometry else 1) + (0 if not words or all(w in head for w in words) else 1)
        match = assess_dataset(record, bbox=bbox, start=start, end=end, variable=variable)
        rank = {"covered": 0, "unknown": 1, "insufficient": 2}[match["status"]]
        scored.append((rank * 10 + score, str(record["id"]), {**record, "match": match}))
    scored.sort(key=lambda item: (item[0], item[1]))
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 500))
    return {
        "ok": True,
        "service": "GeoForge Database",
        "source": "local",
        "catalogue_total": len(records),
        "query": {"keywords": str(q or ""), "bbox": box, "start": start_iso,
                  "end": end_iso, "variables": want_variables,
                  "category": want_category, "delivery": want_delivery},
        "query_semantics": (
            "All keywords must match catalogue text; result total is not catalogue total. "
            "Use bbox, not a town name, to discover covering national/global products. "
            "Search each data category and each KI-mentioned source separately before "
            "concluding that required data was not found."),
        "acquisition_evidence": {
            "catalogue_only": True, "live_delivery": "not_checked",
            "subset_estimate": "not_checked", "model_ready": False,
            "next_action": "request_exact_subset_estimate_before_acquisition_approval",
        },
        "total": len(scored),
        "offset": offset,
        "limit": limit,
        "datasets": [item[2] for item in scored[offset:offset + limit]],
    }


def search_catalogue(*, q: str = "", offset: int = 0, limit: int = 25,
                     client: Client | None = None, bbox=None, start=None, end=None,
                     variable: str = "", category: str = "", delivery: str = "",
                     resolve_dataset_id: str = "", time_step: str = "",
                     describe_dataset_id: str = "") -> dict:
    """App-level catalogue query shared by UI, API Agents and CLI.

    Filters the app's local copy of the catalogue.  The server is only asked to
    refresh that copy.  An explicit ``client`` (tests) queries the server directly.
    """
    if describe_dataset_id and resolve_dataset_id:
        raise ValueError("Choose either describe or resolve in one request")
    if describe_dataset_id:
        return describe_dataset(describe_dataset_id, client=client)
    if resolve_dataset_id:
        return resolve_dataset(resolve_dataset_id, bbox=bbox, start=start, end=end,
                               variable=variable, time_step=time_step, client=client)
    if client is not None:
        return _server_search(q=q, offset=offset, limit=limit, client=client)
    store = refresh_catalogue()
    if store.get("datasets"):
        result = local_search(store["datasets"], q=q, bbox=bbox, start=start, end=end,
                              variable=variable, category=category, delivery=delivery,
                              offset=offset, limit=limit)
        result["catalogue_generated_at"] = store.get("generated_at")
        if not store.get("ok"):
            result["stale"] = True
            result["warning"] = ("catalogue copy is stale: " +
                                 str((store.get("error") or {}).get("message") or ""))
        return result
    error = store.get("error") or {}
    raise ObsAccessError(str(error.get("code") or "network_error"),
                         str(error.get("message") or "") or None)


_DESCRIBE_FIELDS = frozenset((
    "describable dataset_id kind source_version n_source_files variables n_variables "
    "coverage bbox time n_steps start end calendar units multi_schema schemas files count "
    "file sample_long_name files_truncated note reason delivery_fallback categorical "
    "n_bands dtype crs crs_source bounds res bands band nodata description name dims "
    "long_name standard_name select_by in_n_files in_files "
    "processing_version units_authority coverage_scope coverage_note"
).split())


def _schema_metadata(value, depth=0):
    """Copy only the describe contract, including per-file schemas, never credentials.

    Do not silently truncate lists: omitted variables would look like absent data.
    The server already reports files_truncated for its sampled member list.
    """
    if depth > 10:
        raise ObsAccessError("invalid_response", "Source schema nesting is too deep")
    if isinstance(value, dict):
        return {k: _schema_metadata(v, depth + 1) for k, v in value.items()
                if k in _DESCRIBE_FIELDS}
    if isinstance(value, list):
        return [_schema_metadata(v, depth + 1) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ObsAccessError("invalid_response", "Invalid source schema metadata")


def describe_dataset(dataset_id: str, *, client: Client | None = None) -> dict:
    """Live, read-only source discovery shared by API agents and CLI bridges.

    Always re-fetch for now; a cached catalogue must not masquerade as a live
    schema. Retain the server's source_version without treating it as a file
    checksum, and do not infer full-product coverage from sampled headers.
    """
    raw = (client or Client()).describe(dataset_id)
    if (not isinstance(raw, dict) or raw.get("dataset_id") != dataset_id
            or type(raw.get("describable")) is not bool):
        raise ObsAccessError("invalid_response", "Invalid dataset schema response")
    variables = raw.get("variables", [])
    if (not isinstance(variables, list) or any(
            not isinstance(v, dict) or not isinstance(v.get("name"), str) or not v["name"]
            for v in variables)):
        raise ObsAccessError("invalid_response", "Invalid source variable list")
    if (len({v['name'] for v in variables}) != len(variables)
            or ("n_variables" in raw and raw["n_variables"] != len(variables))):
        raise ObsAccessError("invalid_response", "Incomplete or duplicate source variable list")
    result = _schema_metadata(raw)
    result.update(ok=True, service="GeoForge Database", source="source_file_schema",
                  observed_at_epoch=time.time(), schema_only=True, model_ready=False,
                  subset_estimate="not_checked", live_delivery="not_checked")
    result["usage"] = (
        "Use exact source names and inspect units/dimensions plus per-file member information. "
        "Header coverage may describe inspected files, not the whole product; estimate your "
        "exact area and period separately. A schema is not data-quality or model-readiness proof. "
        "Only variables marked select_by=variable are advertised as variable selectors; "
        "raster band metadata does not add a band-selection API."
    )
    return result


def resolve_dataset(dataset_id: str, *, client: Client | None = None, **filters) -> dict:
    """Resolve real delivery IDs and persist only allowlisted metadata, never links."""
    raw = (client or Client()).resolve(dataset_id, **filters)
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise ObsAccessError("invalid_response", "Resolver returned no item list")
    fields = ("coverage_complete", "gaps", "estimated_bytes", "spatial_filter_applied",
              "delivery_extent", "requested_bbox", "covers_requested_bbox", "spatial_note")
    result = {k: _public_value(raw[k]) for k in fields if k in raw}
    for flag in ("coverage_complete", "spatial_filter_applied", "covers_requested_bbox"):
        if result.get(flag) is not None and not isinstance(result[flag], bool):
            raise ObsAccessError("invalid_response", "Invalid resolver coverage flag")
    items = []
    for child in raw["items"]:
        if (not isinstance(child, dict) or not isinstance(child.get("id"), str)
                or child.get("parent_id") != dataset_id):
            raise ObsAccessError("invalid_response", "Resolver returned an invalid child")
        item = {k: _public_value(child[k]) for k in
                ("id", "parent_id", "variable", "year", "time_step", "delivery", "size_hint", "bbox")
                if k in child}
        item["size"] = item.get("size_hint")
        if isinstance(item.get("year"), int) and 1 <= item["year"] <= 9999:
            item["start_date"] = f"{item['year']:04d}-01-01"
            item["end_date"] = f"{item['year']:04d}-12-31"
        item["variables"] = [item["variable"]] if item.get("variable") else []
        item["resolution"] = {k: result[k] for k in fields if k in result}
        items.append(item)
    if int(raw.get("total", len(items))) != len(items):
        raise ObsAccessError("invalid_response", "Incomplete resolver result; refusing partial delivery list")
    if len({i["id"] for i in items}) != len(items):
        raise ObsAccessError("invalid_response", "Resolver returned duplicate child IDs")
    result.update(ok=True, service="GeoForge Database", source="resolver", total=len(items), items=items)
    request = {"dataset_id": dataset_id, **filters}
    result["request"] = request
    result["generated_at_epoch"] = time.time()
    key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    _atomic_json(catalogue_store_path().parent / "resolved" / f"{key}.json", result)
    return result


def resolved_records() -> list[dict]:
    records = []
    for path in sorted((catalogue_store_path().parent / "resolved").glob("*.json")):
        doc = _read_snapshot(path) or {}
        if time.time() - float(doc.get("generated_at_epoch") or 0) <= CATALOGUE_STORE_TTL:
            records.extend(doc.get("items") or [])
    return records


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_snapshot(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def prepare_catalogue_snapshot(project: Path, *, client: Client | None = None,
                               force: bool = False,
                               cache_seconds: int = CATALOGUE_CACHE_SECONDS,
                               max_items: int = 20000) -> Path:
    """Materialize a per-project copy of the catalogue for CLIs in snapshot mode.

    Without an explicit client the copy is taken from the app-level store so
    the server is not paged once per project.
    """
    path = Path(project).resolve() / CATALOGUE_SNAPSHOT
    if client is None:
        _atomic_json(path, refresh_catalogue(force=force))
        return path
    refresh_catalogue(client=client, force=force, path=path, ttl=cache_seconds,
                      max_items=max_items)
    return path


CHILD_ID = re.compile(r"^(?P<parent>[A-Za-z0-9][\w.-]*?)__(?P<variable>[a-z0-9]+)_(?P<year>\d{4})$")

STAMP_FIELDS = ("name", "delivery", "size", "format", "bbox", "point", "start_date",
                "end_date", "parent_id", "temporal", "resolution_deg", "variables")


def size_label(value) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.2f} {unit}".replace(".00", "")
        size /= 1024
    return ""


def _known(text: str, by_id: dict) -> bool:
    return text in by_id


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(text).lower()) if t}


def _fuzzy_id(text: str, by_id: dict) -> str | None:
    """'AVHRR_1km_LANDCOVER_1981_1994' -> 'avhrr_landcover' when exactly one id fits."""
    have = _tokens(text)
    if len(have) < 2:
        return None
    hits = [rid for rid in by_id
            if len(rt := _tokens(rid)) >= 2 and rt <= have]
    if len(hits) == 1:
        return hits[0]
    # several fit: take the most specific one only when it covers all the others
    # ('hwsd_china_raster' over 'hwsd_china' when the text mentions the raster)
    best = max(hits, key=lambda rid: len(_tokens(rid)), default=None)
    if best and all(_tokens(other) <= _tokens(best) for other in hits):
        return best
    return None


def _pinned_id(item: dict, by_id: dict) -> str | None:
    # The item id itself is often the catalogue id (agents name items after datasets).
    candidates = [item.get("dataset_id"), item.get("chosen_source"), item.get("id")]
    for raw in candidates:
        if not isinstance(raw, str) or not raw.strip():
            continue
        text = raw.strip()
        if _known(text, by_id):
            return text
        # tolerate "faostat_china (csv, served, 22 KB)" style annotations
        head = re.split(r"[\s(,;:]", text, maxsplit=1)[0]
        if head in by_id:
            return head
    for raw in candidates:
        if isinstance(raw, str) and (fuzzy := _fuzzy_id(raw, by_id)):
            return fuzzy
    return None


def stamp_inventory(inventory: dict, *, catalogue: dict | None = None, project: Path | None = None) -> list[str]:
    """Attach catalogue facts to every inventory item pinned to a dataset id.

    Sets ``dataset_id``, ``delivery`` and a ``catalogue`` block copied from the
    app's local catalogue copy, and upgrades ``missing`` to ``resolved`` because
    the source is now known.  An explicit ``dataset_id`` that the catalogue does
    not contain is an error returned to the agent; nothing is invented.
    Without a catalogue copy the inventory is left untouched.
    """
    errors = []
    regular_items = []
    for item in (inventory or {}).get('items') or []:
        if not isinstance(item, dict):
            continue
        if item.get('acquisition_id') or item.get('delivery') == 'subset':
            from . import obs_subset
            try:
                if project is None:
                    raise ValueError('Acquisition selection requires a project')
                obs_subset.stamp_item(project, item)
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append(f"item {item.get('id')!r}: {error}")
        else:
            regular_items.append(item)
    if not regular_items:
        return errors
    store = catalogue if catalogue is not None else refresh_catalogue()
    by_id = {str(d.get("id")): d for d in store.get("datasets") or [] if d.get("id")}
    if catalogue is None:
        by_id.update({d["id"]: d for d in resolved_records() if d.get("id")})
    if not by_id:
        return errors + [f"item {item.get('id')!r}: catalogue unavailable; resolve the selected dataset first"
                         for item in regular_items if item.get("dataset_id")]
    # A whole-product parent (e.g. national CMFD, 242 GB) is never a download unit.
    subsets: dict[str, list[str]] = {}
    for d in by_id.values():
        if d.get("parent_id"):
            subsets.setdefault(str(d["parent_id"]), []).append(str(d["id"]))
    for item in regular_items:
        if not isinstance(item, dict):
            continue
        explicit = item.get("dataset_id")
        if explicit and not _known(str(explicit).strip(), by_id):
            errors.append(
                f"item {item.get('id')!r}: dataset_id {explicit!r} is not in the GeoForge Database "
                "catalogue/resolver cache; call resolve with the product, variables and period "
                "and use an actually returned id")
            continue
        pinned = _pinned_id(item, by_id)
        if not pinned:
            continue
        if pinned in subsets and project is not None:
            # A whole product is only usable as a server clip. The host joins the
            # item to the agent's estimate for this study area; the agent need
            # not copy ids by hand.
            from . import obs_subset
            try:
                obs_subset.stamp_item(project, item)
                continue
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append(f"item {item.get('id')!r}: {pinned} is a whole-product parent "
                              f"({size_label(by_id[pinned].get('size')) or 'very large'}) and is only "
                              f"usable as a server clip, but {error}")
                continue
        if pinned in subsets:
            errors.append(
                f"item {item.get('id')!r}: {pinned} is a whole-product parent "
                f"({size_label(by_id[pinned].get('size')) or 'very large'}) and is never downloaded whole. "
                "Either put the acquisition_id of your estimate_clip for this study area on the item "
                "(server-side clip), or use search_catalogue with parent_id to get the exact delivery "
                f"units, or pick a pre-cut regional subset if one covers the study area "
                f"(available: {', '.join(subsets[pinned])}). Never construct child IDs yourself.")
            continue
        child = CHILD_ID.match(pinned)
        record = by_id[pinned]
        resolution = record.get("resolution") or {}
        if resolution.get("coverage_complete") is False or resolution.get("covers_requested_bbox") is False:
            errors.append(f"item {item.get('id')!r}: resolver reports missing variables/years or spatial coverage; revise the request before approval")
            continue
        item["dataset_id"] = pinned
        item["delivery"] = "manual" if child else record.get("delivery")
        item["catalogue"] = {k: record.get(k) for k in STAMP_FIELDS
                             if record.get(k) not in (None, "", [])}
        if project is not None and not child:
            # A study bbox on the item and a dataset that is manual or too big to
            # serve: try the server clip ourselves (read-only estimate). The agent
            # should not have to remember; the host decides from the facts.
            from . import obs_subset
            if obs_subset.prefer_clip(project, item, record):
                continue
        if child:
            item["catalogue"].update({k: record[k] for k in
                ("variable", "year", "time_step", "resolution") if k in record})
        if item.get("status") == "missing":
            item["status"] = "resolved"
            item["needs_user"] = False
            item["agent_resolvable"] = True
    return errors


_STOP_TOKENS = {"the", "and", "for", "with", "from", "use", "using", "run", "model", "data",
                "simulate", "simulation", "please", "then", "only", "plan", "first", "nasa", "power"}
# Chinese place names as they appear in catalogue ids and English names.  A small
# bridge until the catalogue carries region_names in both languages.
_CJK_ALIASES = {
    "淮河": ["huai", "huaihe"], "蚌埠": ["bengbu"], "长江": ["yangtze", "changjiang"],
    "黄河": ["yellow river", "huanghe"], "海河": ["haihe"], "珠江": ["pearl river", "zhujiang"],
    "松花江": ["songhua"], "松花": ["songhua"], "黑河": ["heihe"], "澜沧江": ["lancang"],
    "澜沧": ["lancang"], "怒江": ["nujiang"], "雅鲁藏布": ["yarlung"], "太湖": ["taihu"],
    "洪泽湖": ["hongzehu"], "洪泽": ["hongzehu"], "赣江": ["ganjiang"], "汉江": ["hanjiang"],
    "滁河": ["chuhe"], "秦淮": ["qinhuai"], "王家坝": ["wangjiaba"], "息县": ["xixian"],
    "拉萨": ["lhasa"], "嘉陵江": ["jialingjiang"], "嘉陵": ["jialingjiang"], "宜昌": ["yichang"],
    "漳卫": ["zhangwei"], "滹沱": ["hutuo"], "潮河": ["chaohe"], "葫芦河": ["huluhe"],
    "武汉": ["wuhan"], "南京": ["nanjing"], "扬州": ["yangzhou"], "合肥": ["hefei"],
    "龙门": ["longmen"], "龙盘": ["longpan"], "新疆": ["xinjiang"], "西藏": ["tibet", "xizang"],
    "青藏": ["tibetan plateau", "qinghai"], "中国": ["china"], "蒙古": ["mongolia"],
}


_BROAD_ALIASES = {"china", "xinjiang", "tibet", "xizang", "tibetan plateau", "qinghai", "mongolia"}


def study_terms(*texts: str) -> list[tuple[str, float]]:
    """(term, weight) pairs from free text: Latin words, ids such as 51080, CJK runs,
    their bigrams, and English aliases of Chinese place names.  Weights: station ids
    and place-name aliases count more than ordinary words."""
    out: list[tuple[str, float]] = []
    for text in texts:
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|\d{4,}|[\u4e00-\u9fff]{2,}", str(text or "")):
            if re.fullmatch(r"(19|20)\d\d", tok):
                continue                                   # a year is not a place
            if re.fullmatch(r"[\u4e00-\u9fff]+", tok):
                pieces = [tok[i:i + n] for n in (2, 3, 4) for i in range(len(tok) - n + 1)]
                for piece in pieces:
                    for alias in _CJK_ALIASES.get(piece, []):
                        # a country or province narrows little; a river or station a lot
                        out.append((alias, 0.5 if alias in _BROAD_ALIASES else 2.0))
                out.extend((tok[i:i + 2], 1.0) for i in range(len(tok) - 1))
            elif re.fullmatch(r"\d{4,}", tok):
                out.append((tok, 4.0))        # a station/gauge number is the most specific term
            elif tok.lower() not in _STOP_TOKENS:
                out.append((tok, 1.0))
    seen: set[str] = set()
    return [(t, w) for t, w in out if not (t.lower() in seen or seen.add(t.lower()))]


def study_matches(records: list[dict], *texts: str, limit: int = 12) -> list[dict]:
    """Catalogue records that match the study description, best first.

    Generic terms (ones that occur in more than 3% of the catalogue, such as
    数据 or 模拟) carry no weight; a record needs a specific hit — a station id, a
    place-name alias, or a rare term.  Whole-product parents that have a
    regional subset in the catalogue rank below their subset."""
    terms = study_terms(*texts)
    if not terms or not records:
        return []
    blobs = [(r, _blob(r)) for r in records if isinstance(r, dict) and r.get("id")]
    n = max(1, len(blobs))
    df = {t: sum(1 for _r, b in blobs if t.lower() in b) for t, _w in terms}
    specific = {t: w for t, w in terms if df[t] and df[t] <= max(3, int(0.03 * n))}
    if not specific:
        return []
    subsets = {str(r.get("parent_id")) for r, _b in blobs if r.get("parent_id")}
    scored: list[tuple[float, str, dict]] = []
    for record, blob in blobs:
        score = sum(w for t, w in specific.items() if t.lower() in blob)
        if score <= 0:
            continue
        if str(record["id"]) in subsets:
            score -= 0.75
        scored.append((-score, str(record["id"]), record))
    scored.sort()
    return [r for _s, _i, r in scored[:limit]]


def study_hint_block(records: list[dict], *texts: str, limit: int = 12) -> str:
    """Prompt block: what the GeoForge Database holds for this study."""
    matches = study_matches(records, *texts, limit=limit)
    if not matches:
        return ""
    lines = ["[GEOFORGE DATABASE — AVAILABLE FOR THIS STUDY]",
             "GeoForge matched these candidate records by study-description text, not by model grid. "
             "A basin-name match is not a grid-specific download. Before choosing forcing data, "
             "determine the model grid cells or extent and query their bbox, required variables "
             "and period. Check actual spatial coverage and delivery granularity; bbox filtering "
             "does not clip a file. Prefer matching grid/tile records or a verified clipping service "
             "when available. If only basin-wide or national files exist, disclose their extent, "
             "download size and required local extraction, and ask the user to choose before "
             "pinning that fallback. Never silently substitute a Huai basin package for grid data. "
             "'served' downloads automatically after approval; "
             "'manual' means GeoForge hands the download link to the user after approval and the "
             "run waits for the files — it is a normal choice, not a dead end. Pin exact ids."]
    for d in matches:
        period = f"{d.get('start_date') or '?'}..{d.get('end_date') or '?'}" if d.get("start_date") or d.get("end_date") else ""
        names = _variable_names(d)[:6]
        cov = d.get("bbox") or d.get("point") or d.get("spatial_coverage") or ""
        parts = [f"  - {d['id']}", f"{d.get('delivery') or '?'}"]
        if d.get("size"):
            parts.append(size_label(d["size"]))
        if period:
            parts.append(period)
        if d.get("dataset_kind") or d.get("type"):
            parts.append(str(d.get("dataset_kind") or d.get("type")))
        if names:
            parts.append("vars " + ",".join(names))
        if cov:
            parts.append(f"cov {cov}")
        if d.get("parent_id"):
            parts.append(f"subset of {d['parent_id']}")
        lines.append(" | ".join(parts))
    return "\n".join(lines) + "\n"


def manual_handoff_message(info: dict) -> str:
    """What the user reads for a manual (Baidu) delivery; the Agent never sees it."""
    name = str(info.get("name") or info.get("dataset_id") or "Dataset")
    size = size_label(info.get("size") or info.get("size_hint")) or "size not reported"
    pwd = str(info.get("baidu_pwd") or "")
    lines = [f"{name} ({size}) is delivered through Baidu Pan. Download it and place it "
             "exactly at the destination below.", "", f"Extraction code: {pwd or 'not required'}"]
    if info.get("path_in_share"):
        lines += ["", f"Inside the share, download only this file: {info['path_in_share']}"]
    if info.get("instructions"):
        lines += ["", str(info["instructions"])]
    lines += ["", "Baidu Pan can be slow or unavailable outside China; ask the group owner "
              "for an alternate transfer if needed."]
    return "\n".join(lines)


def planning_snapshot_prompt(path: Path) -> str:
    """Contract text shared by every provider during data-aware planning."""
    payload = _read_snapshot(path) or {}
    state = (f"current ({len(payload.get('datasets') or [])} records)"
             if payload.get("ok") else
             f"unavailable ({(payload.get('error') or {}).get('message') or 'unknown error'})")
    stale = " A stale cached list is present; identify it as stale." if payload.get("stale") else ""
    return (
        "[GEOFORGE DATABASE — HOST-OWNED DATA SERVICE]\n"
        "GeoForge Desktop owns authentication, catalogue access, downloads and checksum "
        "verification for the whole app; no KI or Agent receives its token.\n"
        + DATA_DISCOVERY_RULES +
        f"Sanitized catalogue snapshot: {Path(path).resolve()}\n"
        f"Snapshot status: {state}.{stale}\n"
        "Inspect this metadata while planning and compare exact variables, units, spatial/"
        "temporal coverage and format with every selected KI. Pin an exact dataset id only "
        "when the record supports it. If the catalogue is unavailable or has no match, say so "
        "and ask the user; never invent availability, a download, or substitute data. Do not "
        "download during PLANNING. After approval, GeoForge performs the actual retrieval.\n"
    )
