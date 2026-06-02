from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from core.config import settings


def _fernet() -> Fernet:
    material = settings.FIELD_ENCRYPTION_KEY or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
