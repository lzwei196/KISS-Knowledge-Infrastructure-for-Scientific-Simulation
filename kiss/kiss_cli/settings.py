"""Persistent app settings: API keys, default provider, general options.

The gap this fills was found by using the app as a user: with no key in the
environment, the API providers simply did not exist — no way to see them, no
way to add a key, no explanation. A GUI cannot ask people to export environment
variables; it needs a settings screen whose values persist.

Keys are stored in the platform data directory with 0600 permissions and
loaded into the process environment at startup (fill-gaps only, so a real
environment variable still wins). Persisted keys are returned to the UI only
as a masked tail — the full value never travels back out.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .firstrun import data_dir

KEY_NAMES = ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
             "OPENAI_API_KEY", "OPENROUTER_API_KEY")
KIMI_SECURITY_MODES = {"scoped", "full"}
PROXY_MODES = {"auto", "manual", "off"}
GITHUB_PROXY_TARGET = "network:github"
DEFAULT_PROXY_PROVIDERS = (GITHUB_PROXY_TARGET, "cli:claude", "cli:codex")
PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
)
# A Desktop settings change should affect this app process, not permanently
# rewrite the user's Terminal environment. Remember what Finder/shell supplied
# when GeoForge started so switching Auto/Manual/Off remains reversible.
_BASE_PROXY_ENV = {key: os.environ.get(key) for key in PROXY_ENV_KEYS}


def _path() -> Path:
    return data_dir() / "settings.json"


def load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.parent.chmod(0o700)      # keys live here; the file mode alone is not
    except OSError:                # enough when the directory is group-writable
        pass
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass


def apply_to_env() -> None:
    """Adopt saved API keys into the app process.

    Proxy policy is provider-specific, so it is applied to each child CLI or
    HTTP request rather than mutating the whole desktop process.
    """
    data = load()
    keys = data.get("api_keys") or {}
    for k, v in keys.items():
        if k in KEY_NAMES and v and not os.environ.get(k):
            os.environ[k] = v


def _normalise_proxy_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("proxy address is required in manual mode")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https", "socks5", "socks5h"}:
        raise ValueError("proxy must start with http://, https://, socks5://, or socks5h://")
    if not parsed.hostname:
        raise ValueError("proxy address has no host")
    if parsed.username or parsed.password:
        raise ValueError("proxy credentials are not stored here; use a local authenticated proxy")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError(f"invalid proxy port: {error}") from None
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("proxy address must not contain a path, query, or fragment")
    return raw.rstrip("/")


def detected_system_proxy() -> str:
    """Return the Mac/Windows/environment proxy Python would actually use."""
    try:
        proxies = urllib.request.getproxies()
    except (OSError, ValueError):
        return ""
    candidate = (proxies.get("https") or proxies.get("http") or
                 proxies.get("socks") or "")
    if candidate and "://" not in candidate:
        candidate = "http://" + candidate
    try:
        return _normalise_proxy_url(candidate) if candidate else ""
    except ValueError:
        return ""


def proxy_mode(data: dict | None = None) -> str:
    mode = (data if data is not None else load()).get("proxy_mode", "auto")
    return mode if mode in PROXY_MODES else "auto"


def proxy_details(data: dict | None = None) -> dict:
    current = data if data is not None else load()
    mode = proxy_mode(current)
    manual = str(current.get("proxy_url") or "").strip()
    effective = (manual if mode == "manual" else
                 detected_system_proxy() if mode == "auto" else "")
    return {
        "proxy_mode": mode,
        "proxy_url": manual,
        "proxy_effective": effective,
        "proxy_source": ("manual" if mode == "manual" else
                         "system" if effective else "none"),
        "proxy_providers": sorted(proxy_providers(current)),
    }


def proxy_providers(data: dict | None = None) -> set[str]:
    current = data if data is not None else load()
    raw = current.get("proxy_providers")
    if not isinstance(raw, list):
        return set(DEFAULT_PROXY_PROVIDERS)
    selected = {str(value) for value in raw if isinstance(value, str)}
    # Older releases had no separate updater target. Adopt the same route on
    # first upgrade so a proxy that already fixed Claude/Codex also fixes KI
    # updates. Once the new UI is saved, an explicit unchecked choice wins.
    if int(current.get("proxy_targets_version") or 0) < 1:
        selected.add(GITHUB_PROXY_TARGET)
    return selected


def provider_uses_proxy(provider: str, data: dict | None = None) -> bool:
    current = data if data is not None else load()
    return proxy_mode(current) != "off" and provider in proxy_providers(current)


def with_provider_proxy(provider: str, env: dict | None = None,
                        data: dict | None = None) -> dict:
    """Return a child environment with proxy policy for one AI provider.

    Unselected providers have proxy variables removed from their child only;
    selected providers receive the effective automatic/manual address. This
    keeps Claude/Codex proxy routing from silently changing Kimi or DeepSeek.
    """
    current = data if data is not None else load()
    result = dict(os.environ if env is None else env)
    for key in PROXY_ENV_KEYS:
        result.pop(key, None)
    details = proxy_details(current)
    url = details["proxy_effective"] if provider_uses_proxy(provider, current) else ""
    if not url:
        return result
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                "http_proxy", "https_proxy", "all_proxy"):
        result[key] = url
    bypass = (_BASE_PROXY_ENV.get("NO_PROXY") or
              _BASE_PROXY_ENV.get("no_proxy") or
              "127.0.0.1,localhost,::1")
    result["NO_PROXY"] = bypass
    result["no_proxy"] = bypass
    return result


def proxy_url_for(provider: str, data: dict | None = None) -> str:
    current = data if data is not None else load()
    if not provider_uses_proxy(provider, current):
        return ""
    return str(proxy_details(current).get("proxy_effective") or "")


def masked() -> dict:
    """Settings for the UI: keys reduced to a recognisable tail."""
    s = load()
    out = {"default_provider": s.get("default_provider", ""),
           "kimi_security_mode": kimi_security_mode(s),
           "api_keys": {}, **proxy_details(s)}
    for k in KEY_NAMES:
        v = (s.get("api_keys") or {}).get(k) or os.environ.get(k) or ""
        out["api_keys"][k] = (f"…{v[-4:]}" if v else "")
    return out


def kimi_security_mode(data: dict | None = None) -> str:
    """The Kimi file-access mode, defaulting safely for old settings files."""
    mode = (data if data is not None else load()).get(
        "kimi_security_mode", "scoped")
    return mode if mode in KIMI_SECURITY_MODES else "scoped"


def update(payload: dict) -> None:
    """Apply a settings change from the UI.

    A key value that looks like our own mask ("…abcd") means unchanged; an
    empty string means delete; anything else is the new key.
    """
    s = load()
    s.setdefault("api_keys", {})
    for k, v in (payload.get("api_keys") or {}).items():
        if k not in KEY_NAMES or (v or "").startswith("…"):
            continue
        if v:
            s["api_keys"][k] = v
            os.environ[k] = v
        else:
            s["api_keys"].pop(k, None)
            os.environ.pop(k, None)
    if "default_provider" in payload:
        dp = payload["default_provider"]
        if dp:
            from . import api as _api
            from . import providers as _prov
            kind, _, pname = dp.partition(":")
            ok = (pname in _prov.PROVIDERS) if kind == "cli" else                  (pname in _api.PROVIDERS) if kind == "api" else False
            if not ok:
                raise ValueError(f"unknown provider {dp!r}")
        s["default_provider"] = dp
    if "kimi_security_mode" in payload:
        mode = payload["kimi_security_mode"]
        if mode not in KIMI_SECURITY_MODES:
            raise ValueError(f"unknown Kimi security mode {mode!r}")
        s["kimi_security_mode"] = mode
    if "proxy_mode" in payload:
        mode = payload["proxy_mode"]
        if mode not in PROXY_MODES:
            raise ValueError(f"unknown proxy mode {mode!r}")
        s["proxy_mode"] = mode
    if "proxy_url" in payload:
        raw = str(payload.get("proxy_url") or "").strip()
        if raw:
            s["proxy_url"] = _normalise_proxy_url(raw)
        else:
            s.pop("proxy_url", None)
    if proxy_mode(s) == "manual" and not s.get("proxy_url"):
        raise ValueError("proxy address is required in manual mode")
    if "proxy_providers" in payload:
        requested = payload.get("proxy_providers")
        if not isinstance(requested, list) or not all(
                isinstance(item, str) for item in requested):
            raise ValueError("proxy providers must be a list")
        from . import api as _api
        from . import providers as _prov
        allowed = ({GITHUB_PROXY_TARGET} |
                   {f"cli:{name}" for name in _prov.PROVIDERS} |
                   {f"api:{name}" for name in _api.PROVIDERS})
        unknown = sorted(set(requested) - allowed)
        if unknown:
            raise ValueError(f"unknown proxy providers: {', '.join(unknown)}")
        s["proxy_providers"] = sorted(set(requested))
        s["proxy_targets_version"] = 1
    save(s)
