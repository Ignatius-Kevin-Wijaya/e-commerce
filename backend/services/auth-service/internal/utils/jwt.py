"""
JWT token utilities — create and decode JSON Web Tokens.

LEARNING NOTES:
- JWT has 3 parts: header.payload.signature (separated by dots).
- The payload carries claims like user_id and expiration time.
- The signature ensures nobody tampered with the token.
- Access tokens are SHORT-lived (30 min) — limits damage if stolen.
- Refresh tokens are LONGER-lived (7 days) — used to get new access tokens.
- We store refresh tokens in the DB (Session table) so we can revoke them.
"""

import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from jose import JWTError, jwt

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))


def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a short-lived access token."""
    to_encode = data.copy()
    now = datetime.utcnow()
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"iat": now, "jti": str(uuid.uuid4()), "exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a longer-lived refresh token."""
    to_encode = data.copy()
    now = datetime.utcnow()
    expire = now + (expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))
    # jti makes each refresh token unique even when the same user logs in repeatedly
    # within the same second during load tests.
    to_encode.update({"iat": now, "jti": str(uuid.uuid4()), "exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """
    Decode and verify a JWT token.
    Returns the payload dict if valid, None if invalid/expired.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
