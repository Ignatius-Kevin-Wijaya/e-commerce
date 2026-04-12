"""
Auth service — business logic layer.

LEARNING NOTES:
- The service layer contains business rules (e.g., "passwords must be ≥ 8 chars").
- It calls the repository for DB operations and utils for hashing/JWT.
- It does NOT know about HTTP — that's the handler's job.
- This separation lets you reuse the same logic in CLI tools, workers, etc.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from internal.model.user import Session as SessionModel
from internal.model.user import User
from internal.repository.user_repository import UserRepository
from internal.utils.jwt import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from internal.utils.password import hash_password, verify_password


class AuthServiceError(Exception):
    """Custom exception for auth business logic errors."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AuthService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def register(
        self,
        email: str,
        username: str,
        password: str,
        full_name: Optional[str] = None,
    ) -> User:
        """Register a new user account."""
        # Check email uniqueness
        if await self.user_repo.find_by_email(email):
            raise AuthServiceError("Email already registered", 409)

        # Check username uniqueness
        if await self.user_repo.find_by_username(username):
            raise AuthServiceError("Username already taken", 409)

        # Validate password strength
        if len(password) < 8:
            raise AuthServiceError("Password must be at least 8 characters")

        # Create user with hashed password (offloaded to thread to unblock event loop)
        hashed = await asyncio.to_thread(hash_password, password)
        user = User(
            email=email,
            username=username,
            hashed_password=hashed,
            full_name=full_name,
        )
        return await self.user_repo.create(user)

    async def login(
        self,
        email: str,
        password: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> dict:
        """
        Authenticate and return access + refresh tokens.
        Returns: {"access_token": "...", "refresh_token": "...", "token_type": "bearer"}
        """
        user = await self.user_repo.find_by_email(email)
        if not user or not await asyncio.to_thread(verify_password, password, user.hashed_password):
            raise AuthServiceError("Invalid email or password", 401)

        if not user.is_active:
            raise AuthServiceError("Account is deactivated", 403)

        # Create JWT tokens
        token_data = {"sub": str(user.id), "email": user.email, "is_admin": user.is_admin}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        # Store refresh token in DB for revocation support
        session = SessionModel(
            user_id=user.id,
            refresh_token=refresh_token,
            user_agent=user_agent,
            ip_address=ip_address,
            expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )
        await self.user_repo.create_session(session)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    async def refresh_access_token(self, refresh_token: str) -> dict:
        """Use a refresh token to get a new access token (token rotation)."""
        # Verify the refresh token is valid JWT
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise AuthServiceError("Invalid refresh token", 401)

        # Check it exists in DB and is not revoked
        session = await self.user_repo.find_session_by_token(refresh_token)
        if not session:
            raise AuthServiceError("Refresh token revoked or expired", 401)

        if session.expires_at < datetime.utcnow():
            await self.user_repo.revoke_session(session.id)
            raise AuthServiceError("Refresh token expired", 401)

        # Revoke old refresh token and issue new pair (rotation)
        await self.user_repo.revoke_session(session.id)

        user = await self.user_repo.find_by_id(session.user_id)
        if not user:
            raise AuthServiceError("User not found", 404)

        token_data = {"sub": str(user.id), "email": user.email, "is_admin": user.is_admin}
        new_access = create_access_token(token_data)
        new_refresh = create_refresh_token(token_data)

        # Store new refresh token
        new_session = SessionModel(
            user_id=user.id,
            refresh_token=new_refresh,
            expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )
        await self.user_repo.create_session(new_session)

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
        }

    async def logout(self, refresh_token: str) -> None:
        """Revoke a refresh token (logout from one device)."""
        session = await self.user_repo.find_session_by_token(refresh_token)
        if session:
            await self.user_repo.revoke_session(session.id)

    async def logout_all(self, user_id: UUID) -> None:
        """Revoke all sessions (logout from all devices)."""
        await self.user_repo.revoke_all_user_sessions(user_id)

    async def get_current_user(self, user_id: UUID) -> Optional[User]:
        """Get user profile by ID."""
        user = await self.user_repo.find_by_id(user_id)
        if not user or not user.is_active:
            raise AuthServiceError("User not found", 404)
        return user
