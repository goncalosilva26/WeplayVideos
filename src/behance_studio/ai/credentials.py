"""API key storage.

Keys are stored in the operating system's credential vault through
``keyring`` (Windows Credential Manager on Windows). They are never written
to settings files, project files or exports. If no secure vault is
available, keys can come from environment variables or be kept in memory
for the current session only.
"""

from __future__ import annotations

import os

from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)

SERVICE = "BehanceStudio"
ENV_VARS = {
    "openai": ["BEHANCE_STUDIO_OPENAI_API_KEY", "OPENAI_API_KEY"],
    "anthropic": ["BEHANCE_STUDIO_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"],
    "local": ["BEHANCE_STUDIO_LOCAL_API_KEY"],
}
_session: dict[str, str] = {}


def _keyring():
    try:
        import keyring
        from keyring.backends import fail

        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring):
            return None
        return keyring
    except Exception:  # noqa: BLE001
        return None


def secure_storage_available() -> bool:
    return _keyring() is not None


def storage_description() -> str:
    kr = _keyring()
    if kr is None:
        return "No secure credential vault is available; keys are kept for this session only (or set an environment variable)."
    name = type(kr.get_keyring()).__name__
    if "Win" in name:
        return "Stored in Windows Credential Manager."
    if "macOS" in name or "Keychain" in name:
        return "Stored in the macOS Keychain."
    return f"Stored in the system keyring ({name})."


def set_api_key(provider: str, key: str) -> str:
    key = (key or "").strip()
    kr = _keyring()
    if not key:
        delete_api_key(provider)
        return "deleted"
    if kr is not None:
        try:
            kr.set_password(SERVICE, provider, key)
            _session.pop(provider, None)
            return "keyring"
        except Exception as exc:  # noqa: BLE001
            log.warning("Keyring write failed: %s", exc)
    _session[provider] = key
    return "session"


def get_api_key(provider: str) -> str | None:
    for var in ENV_VARS.get(provider, []):
        value = os.environ.get(var)
        if value:
            return value.strip()
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(SERVICE, provider)
            if value:
                return value
        except Exception as exc:  # noqa: BLE001
            log.warning("Keyring read failed: %s", exc)
    return _session.get(provider)


def delete_api_key(provider: str) -> None:
    _session.pop(provider, None)
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, provider)
        except Exception:  # noqa: BLE001 - nothing stored
            pass


def has_api_key(provider: str) -> bool:
    return bool(get_api_key(provider))
