import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: uuid.UUID | str) -> str:
    """Create a JWT that expires exactly JWT_EXPIRE_MINUTES (1 hour) from now.

    `sub` holds the user's id; `exp` is enforced automatically by python-jose
    on decode.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    to_encode: dict[str, Any] = {"sub": str(subject), "iat": now, "exp": expire}
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT. Returns the payload, or None if invalid/expired."""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


def generate_share_token() -> tuple[str, str]:
    """Create a share token for the /join link.

    Returns (raw_token, token_hash). Only the hash is stored in the database,
    so a database leak alone doesn't let an attacker redeem outstanding
    invites -- the same reason passwords are hashed rather than stored.
    The raw token goes only into the emailed link.
    """
    raw_token = secrets.token_urlsafe(32)
    return raw_token, hash_share_token(raw_token)


def hash_share_token(raw_token: str) -> str:
    """Hash a share token for storage/lookup.

    Uses SHA-256 rather than bcrypt: unlike a password, this value is
    already high-entropy random, so a slow hash buys nothing, and a
    deterministic hash lets us look the token up by index on redemption.
    """
    return hashlib.sha256(raw_token.encode()).hexdigest()
