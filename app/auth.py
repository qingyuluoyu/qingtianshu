from __future__ import annotations

import re
import secrets
import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


_ACCOUNT_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9_.-]{3,32}\Z")
_PHONE_PATTERN = re.compile(r"1[3-9]\d{9}\Z")
_PASSWORD_HASHER = PasswordHasher()
_DUMMY_PASSWORD_HASH = _PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


def normalize_account(value: str) -> str:
    account = unicodedata.normalize("NFKC", value).strip().casefold()
    if not _ACCOUNT_PATTERN.fullmatch(account):
        raise ValueError("账号格式不正确")
    return account


def normalize_phone(value: str) -> str:
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))
    if compact.startswith("+86"):
        compact = compact[3:]
    elif compact.startswith("86") and len(compact) == 13:
        compact = compact[2:]
    if not _PHONE_PATTERN.fullmatch(compact):
        raise ValueError("手机号格式不正确")
    return f"+86{compact}"


def validate_password(value: str) -> str:
    if not 8 <= len(value) <= 128:
        raise ValueError("密码长度必须为 8 到 128 个字符")
    return value


def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(validate_password(password))


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        verified = _PASSWORD_HASHER.verify(password_hash or _DUMMY_PASSWORD_HASH, password)
        return bool(password_hash) and verified
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def masked_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    return f"{phone[:6]}****{phone[-4:]}"
