"""
JWT middleware — validates Bearer tokens on protected routes.

LEARNING NOTES:
- Middleware runs BEFORE your route handler sees the request.
- It extracts the JWT from the Authorization header, verifies it,
  and injects the user_id into the request state.
- Routes can then access request.state.user_id.
- This is dependency injection via FastAPI's Depends() mechanism.
"""

import os
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

security = HTTPBearer()


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> UUID:
    """
    FastAPI dependency that extracts and validates the JWT.
    Use as: Depends(get_current_user_id)
    Returns the user UUID from the token's 'sub' claim.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: Optional[str] = payload.get("sub")
        token_type: Optional[str] = payload.get("type")

        if user_id_str is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing 'sub' claim",
            )

        if token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Expected access token, got refresh token",
            )

        return UUID(user_id_str)

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


async def get_admin_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> UUID:
    """
    Like get_current_user_id, but also checks the is_admin claim.
    Use for admin-only routes.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: Optional[str] = payload.get("sub")
        is_admin: bool = payload.get("is_admin", False)

        if user_id_str is None:
            raise HTTPException(status_code=401, detail="Token missing 'sub' claim")

        if not is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

        return UUID(user_id_str)

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
