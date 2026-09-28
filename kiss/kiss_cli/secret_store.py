"""Small, dependency-free storage for nonportable activation tokens.

GeoForge settings are portable JSON, but activation tokens are not settings:
macOS uses a private mode-0600 file, with migration from Keychain; Windows
uses Credential Manager and Linux uses Secret Service. The macOS file is
not encrypted by this module and is readable by other processes of the same
user. It must never be included in agent context or portable settings.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys


class SecretStoreUnavailable(RuntimeError):
    """The platform secret store cannot be used on this machine."""


class SecretStoreError(RuntimeError):
    """The platform secret store rejected an operation."""


def _mac_security():
    try:
        security = ctypes.CDLL(
            "/System/Library/Frameworks/Security.framework/Security")
        core = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    except OSError as error:
        raise SecretStoreUnavailable("macOS Keychain is unavailable") from error

    security.SecKeychainFindGenericPassword.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    security.SecKeychainAddGenericPassword.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
    security.SecKeychainItemModifyAttributesAndData.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
    security.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
    security.SecKeychainItemDelete.restype = ctypes.c_int32
    security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    security.SecKeychainItemFreeContent.restype = ctypes.c_int32
    core.CFRelease.argtypes = [ctypes.c_void_p]
    return security, core


def _mac_find(service: str, account: str):
    security, core = _mac_security()
    service_b = service.encode("utf-8")
    account_b = account.encode("utf-8")
    length = ctypes.c_uint32()
    data = ctypes.c_void_p()
    item = ctypes.c_void_p()
    status = security.SecKeychainFindGenericPassword(
        None, len(service_b), service_b, len(account_b), account_b,
        ctypes.byref(length), ctypes.byref(data), ctypes.byref(item))
    if status == -25300:  # errSecItemNotFound
        return security, core, None, None
    if status != 0:
        raise SecretStoreError(f"macOS Keychain lookup failed ({status})")
    value = ctypes.string_at(data, length.value).decode("utf-8")
    security.SecKeychainItemFreeContent(None, data)
    return security, core, item, value


def _mac_get(service: str, account: str) -> str | None:
    _security, core, item, value = _mac_find(service, account)
    if item:
        core.CFRelease(item)
    return value


def _mac_set(service: str, account: str, secret: str) -> None:
    security, core, item, _value = _mac_find(service, account)
    secret_b = secret.encode("utf-8")
    secret_buffer = ctypes.create_string_buffer(secret_b)
    if item:
        try:
            status = security.SecKeychainItemModifyAttributesAndData(
                item, None, len(secret_b), secret_buffer)
        finally:
            core.CFRelease(item)
    else:
        service_b = service.encode("utf-8")
        account_b = account.encode("utf-8")
        status = security.SecKeychainAddGenericPassword(
            None, len(service_b), service_b, len(account_b), account_b,
            len(secret_b), secret_buffer, None)
    if status != 0:
        raise SecretStoreError(f"macOS Keychain write failed ({status})")


def _mac_delete(service: str, account: str) -> None:
    security, core, item, _value = _mac_find(service, account)
    if not item:
        return
    try:
        status = security.SecKeychainItemDelete(item)
    finally:
        core.CFRelease(item)
    if status != 0:
        raise SecretStoreError(f"macOS Keychain delete failed ({status})")


class _CredentialW(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.c_uint32), ("Type", ctypes.c_uint32),
        ("TargetName", ctypes.c_wchar_p), ("Comment", ctypes.c_wchar_p),
        ("LastWritten", ctypes.c_uint64), ("CredentialBlobSize", ctypes.c_uint32),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", ctypes.c_uint32), ("AttributeCount", ctypes.c_uint32),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


def _win_api():
    try:
        # use_last_error is required for Cred* failures to report the real
        # Windows error (not a stale zero from ctypes' thread-local slot).
        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    except (AttributeError, OSError) as error:
        raise SecretStoreUnavailable("Windows Credential Manager is unavailable") from error
    ptr = ctypes.POINTER(_CredentialW)
    api.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                              ctypes.c_uint32, ctypes.POINTER(ptr)]
    api.CredReadW.restype = ctypes.c_bool
    api.CredWriteW.argtypes = [ctypes.POINTER(_CredentialW), ctypes.c_uint32]
    api.CredWriteW.restype = ctypes.c_bool
    api.CredDeleteW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
    api.CredDeleteW.restype = ctypes.c_bool
    api.CredFree.argtypes = [ctypes.c_void_p]
    return api


def _win_target(service: str, account: str) -> str:
    return f"{service}:{account}"


def _win_get(service: str, account: str) -> str | None:
    api = _win_api()
    pointer = ctypes.POINTER(_CredentialW)()
    if not api.CredReadW(_win_target(service, account), 1, 0,
                         ctypes.byref(pointer)):
        error = ctypes.get_last_error()
        if error == 1168:  # ERROR_NOT_FOUND
            return None
        raise SecretStoreError(f"Credential Manager lookup failed ({error})")
    try:
        credential = pointer.contents
        raw = ctypes.string_at(credential.CredentialBlob,
                               credential.CredentialBlobSize)
        return raw.decode("utf-16-le")
    finally:
        api.CredFree(pointer)


def _win_set(service: str, account: str, secret: str) -> None:
    api = _win_api()
    raw = secret.encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    credential = _CredentialW()
    credential.Type = 1  # CRED_TYPE_GENERIC
    credential.TargetName = _win_target(service, account)
    credential.CredentialBlobSize = len(raw)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = account
    if not api.CredWriteW(ctypes.byref(credential), 0):
        raise SecretStoreError(
            f"Credential Manager write failed ({ctypes.get_last_error()})")


def _win_delete(service: str, account: str) -> None:
    api = _win_api()
    if not api.CredDeleteW(_win_target(service, account), 1, 0):
        error = ctypes.get_last_error()
        if error != 1168:
            raise SecretStoreError(f"Credential Manager delete failed ({error})")


def _linux_tool() -> str:
    executable = shutil.which("secret-tool")
    if not executable:
        raise SecretStoreUnavailable(
            "Secret Service is unavailable (install libsecret/secret-tool)")
    return executable


def _linux_get(service: str, account: str) -> str | None:
    result = subprocess.run(
        [_linux_tool(), "lookup", "service", service, "account", account],
        capture_output=True, text=True, timeout=15, check=False)
    if result.returncode:
        return None
    return result.stdout.rstrip("\n") or None


def _linux_set(service: str, account: str, secret: str) -> None:
    result = subprocess.run(
        [_linux_tool(), "store", f"--label=GeoForge {account}",
         "service", service, "account", account],
        input=secret + "\n", capture_output=True, text=True,
        timeout=30, check=False)
    if result.returncode:
        raise SecretStoreError("Secret Service rejected the token")


def _linux_delete(service: str, account: str) -> None:
    subprocess.run(
        [_linux_tool(), "clear", "service", service, "account", account],
        capture_output=True, timeout=15, check=False)


# ---------------------------------------------------------------------------
# macOS: a private file instead of the login Keychain.
#
# A Keychain item's access list is bound to the reading app's code identity.
# GeoForge Desktop is ad-hoc signed, so every build (and every release update)
# is a new identity and macOS asks the user again.  A file under the user's
# Application Support directory with mode 0600 is readable only by that user
# account, needs no consent dialog, and survives updates.  Windows and Linux
# stores do not have the per-build problem and stay as they are.
# ---------------------------------------------------------------------------

def _file_path(service: str, account: str):
    from .firstrun import data_dir
    import re
    safe = lambda s: re.sub(r"[^A-Za-z0-9._-]", "_", s)[:120]  # noqa: E731
    return data_dir() / "secrets" / f"{safe(service)}.{safe(account)}"


def _file_get(service: str, account: str) -> str | None:
    path = _file_path(service, account)
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None
    except OSError as error:
        raise SecretStoreError(f"cannot read the private token file: {error}") from error


def _file_set(service: str, account: str, secret: str) -> None:
    import os
    import tempfile
    path = _file_path(service, account)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        fd, tmp = tempfile.mkstemp(prefix=".token-", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secret)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as error:
        raise SecretStoreError(f"cannot write the private token file: {error}") from error


def _file_delete(service: str, account: str) -> None:
    try:
        _file_path(service, account).unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise SecretStoreError(f"cannot remove the private token file: {error}") from error


def _mac_get_migrating(service: str, account: str) -> str | None:
    """Private file first; a token still in the Keychain is copied over once."""
    value = _file_get(service, account)
    if value is not None:
        return value
    try:
        legacy = _mac_get(service, account)
    except (SecretStoreUnavailable, SecretStoreError):
        return None
    if legacy:
        _file_set(service, account, legacy)
    return legacy


def get_secret(service: str, account: str) -> str | None:
    if sys.platform == "darwin":
        return _mac_get_migrating(service, account)
    if sys.platform == "darwin":
        return _mac_get(service, account)
    if sys.platform == "win32":
        return _win_get(service, account)
    return _linux_get(service, account)


def set_secret(service: str, account: str, secret: str) -> None:
    if not secret:
        raise ValueError("secret must not be empty")
    if sys.platform == "darwin":
        _file_set(service, account, secret)
    elif sys.platform == "win32":
        _win_set(service, account, secret)
    else:
        _linux_set(service, account, secret)


def delete_secret(service: str, account: str) -> None:
    if sys.platform == "darwin":
        _file_delete(service, account)
    elif sys.platform == "win32":
        _win_delete(service, account)
    else:
        _linux_delete(service, account)
