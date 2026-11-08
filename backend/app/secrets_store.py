"""Encrypts secrets (VLM API keys, webhook tokens, device passwords) before they go into the DB.

The Fernet key comes ONLY from env var TIAM_SECRET_KEY (install.ps1 writes it into config.ps1;
see CLAUDE.md for the dev one-liner). No fallback key, ever (ADR 0006): without it, `available()` is
False and callers must refuse to store secrets.
"""
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

ENV_VAR = "TIAM_SECRET_KEY"


class SecretKeyMissing(RuntimeError):
    pass


def _windows_user_env(name: str) -> Optional[str]:
    """A Windows user environment variable set after this process's parent started (e.g. a VS Code
    terminal opened before it was set) isn't in os.environ; read it where Windows stores it."""
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0]) or None
    except OSError:
        return None


def _fernet() -> Fernet:
    key = os.environ.get(ENV_VAR) or _windows_user_env(ENV_VAR)
    if not key:
        raise SecretKeyMissing(f"{ENV_VAR} is not set: secrets can't be stored")
    return Fernet(key.encode())


def available() -> bool:
    try:
        _fernet()
        return True
    except (SecretKeyMissing, ValueError):
        return False


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: Optional[str]) -> Optional[str]:
    """None when nothing is stored. Raises SecretKeyMissing / InvalidToken (key changed) so a caller
    never silently uses an empty secret."""
    if not ciphertext:
        return None
    return _fernet().decrypt(ciphertext.encode()).decode()


def last4(plaintext: str) -> str:
    """What the API may show of a stored secret."""
    return plaintext[-4:] if len(plaintext) >= 8 else ""


def generate_key() -> str:
    return Fernet.generate_key().decode()


__all__ = ["available", "encrypt", "decrypt", "last4", "generate_key", "SecretKeyMissing", "InvalidToken"]
