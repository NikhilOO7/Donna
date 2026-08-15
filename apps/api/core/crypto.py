"""
Symmetric encryption for secrets at rest.

Customer database credentials are the most sensitive thing this system will
ever store — more sensitive than the meeting content itself, because a leaked
credential grants access to a system Donna does not control and cannot revoke.

They are therefore encrypted in the application layer, not merely protected by
database access control. A Postgres backup, a replica, or a support engineer
with read access to ``data_connections`` must not yield usable credentials.

Key management is deliberately explicit: ``ENCRYPTION_KEY`` must be set, and
production refuses to boot without it (see ``config.production_safety_errors``).
There is no "generate one if missing" convenience path — a key that regenerates
on restart silently makes every stored credential undecryptable, which presents
as data loss rather than as a configuration error.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_fernet = None


class EncryptionUnavailableError(RuntimeError):
    """Raised when a secret is handled without a configured key."""


def _derive_key(raw: str) -> bytes:
    """Accept either a real Fernet key or an arbitrary passphrase.

    A Fernet key is 32 url-safe base64 bytes. Operators reliably paste
    passphrases instead, so anything that isn't already a valid key is
    stretched through SHA-256 — which keeps the system usable without silently
    accepting a weak key as-is.
    """
    raw = (raw or "").strip()
    if not raw:
        raise EncryptionUnavailableError("ENCRYPTION_KEY is not set")
    try:
        from cryptography.fernet import Fernet

        candidate = raw.encode()
        # Round-trips only for a genuine Fernet key.
        Fernet(candidate)
        return candidate
    except Exception:
        digest = hashlib.sha256(raw.encode()).digest()
        return base64.urlsafe_b64encode(digest)


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    from cryptography.fernet import Fernet

    from apps.api.core.config import settings

    _fernet = Fernet(_derive_key(settings.encryption_key or ""))
    return _fernet


def encryption_available() -> bool:
    """True when secrets can be stored. Lets callers fail with a clear 4xx."""
    try:
        _get_fernet()
        return True
    except Exception:
        return False


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for storage. Returns a url-safe token."""
    if plaintext is None:
        raise ValueError("cannot encrypt None")
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a stored secret.

    A failure here almost always means the key changed, so the message says so
    — "invalid token" alone has sent people looking for data corruption that
    isn't there.
    """
    from cryptography.fernet import InvalidToken

    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise EncryptionUnavailableError(
            "Stored secret could not be decrypted. This normally means "
            "ENCRYPTION_KEY changed since the secret was saved — the data is "
            "intact but unreadable with the current key."
        ) from e


def mask(secret: Optional[str], keep: int = 2) -> str:
    """Render a secret for display. Never returns the original."""
    if not secret:
        return ""
    if len(secret) <= keep:
        return "•" * 8
    return secret[:keep] + "•" * 8
