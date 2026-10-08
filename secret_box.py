"""
secret_box.py — encryption for credentials stored in the controller databases.

Every value is encrypted with Fernet using a key derived from SECRET_KEY.
Decryption also accepts the formats older FleetPilot versions wrote, so
existing databases keep working and are re-encrypted on the next save:

* "sha256" modules (vm/storage controllers) used sha256(SECRET_KEY), and
  sha256("") or plain base64 when the key or cryptography was missing.
* "raw32" modules (fans, backup, Corsair) used the first 32 bytes of
  SECRET_KEY, and stored plain text when the key was shorter.
"""
import base64
import hashlib
import logging
import os

logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - cryptography is a hard requirement
    Fernet = None
    InvalidToken = Exception
    logger.error("cryptography is not installed; stored credentials cannot be encrypted")


def _sha256_fernet(secret: bytes):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))


class SecretBox:
    def __init__(self, scheme: str):
        secret = os.environ.get("SECRET_KEY", "").encode()
        self._legacy = []
        if Fernet is None:
            self._primary = None
            return
        if scheme == "raw32" and len(secret) >= 32:
            self._primary = Fernet(base64.urlsafe_b64encode(secret[:32]))
        else:
            self._primary = _sha256_fernet(secret)
        if scheme == "sha256":
            self._legacy.append(_sha256_fernet(b""))
        legacy_secret = os.environ.get("FLEETPILOT_LEGACY_SECRET_KEY", "").encode()
        if legacy_secret:
            self._legacy.append(_sha256_fernet(legacy_secret))
            if len(legacy_secret) >= 32:
                self._legacy.append(Fernet(base64.urlsafe_b64encode(legacy_secret[:32])))
        self._scheme = scheme

    def encrypt(self, value: str) -> str:
        if self._primary is None:
            raise RuntimeError("cryptography is required to store credentials")
        return self._primary.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        if not value or self._primary is None:
            return value
        for f in [self._primary] + self._legacy:
            try:
                return f.decrypt(value.encode()).decode()
            except (InvalidToken, ValueError):
                continue
        if self._scheme == "sha256":
            try:  # base64 written when cryptography was unavailable
                return base64.b64decode(value.encode(), validate=True).decode()
            except Exception:
                pass
        return value  # legacy plain text
