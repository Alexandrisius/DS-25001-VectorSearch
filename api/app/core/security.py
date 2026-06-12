"""JWT, bcrypt, шифрование секретов."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.core.exceptions import AuthError

# bcrypt для хеширования пароля админа
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:
        return False


def create_access_token(
    subject: str,
    extra: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Создать JWT токен."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=settings.jwt_expire_hours))
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": datetime.now(timezone.utc),
        "exp": expire,
        "type": "admin_access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Декодировать и валидировать JWT токен. Raises AuthError при ошибке."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise AuthError(f"Невалидный или истёкший токен: {e}") from e

    if payload.get("type") != "admin_access":
        raise AuthError("Неверный тип токена")
    return payload


# =============================================================================
# Fernet encryption для API ключей OpenRouter
# =============================================================================

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = get_settings().encryption_key.encode()
        if not key or key == b"":
            raise RuntimeError("ENCRYPTION_KEY не настроен")
        _fernet = Fernet(key)
    return _fernet


def encrypt_secret(plaintext: str) -> bytes:
    """Зашифровать строку (например, API ключ)."""
    if not plaintext:
        return b""
    return _get_fernet().encrypt(plaintext.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    """Расшифровать строку."""
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(bytes(ciphertext)).decode()
    except InvalidToken as e:
        raise RuntimeError("Не удалось расшифровать секрет (проверьте ENCRYPTION_KEY)") from e


__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
    "encrypt_secret",
    "decrypt_secret",
]
