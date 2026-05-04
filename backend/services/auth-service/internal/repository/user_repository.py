"""
User repository — database access layer.

LEARNING NOTES:
- The repository pattern separates DB queries from business logic.
- This makes testing easier: you can mock the repository in unit tests.
- We use SQLAlchemy's async session for non-blocking DB calls.
- Each method does ONE thing: find, create, update, etc.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from internal.model.user import Session, User


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _detach_and_release(self, entity):
        """
        Return ORM objects as detached instances so the checked-out DB connection
        can go back to the pool before CPU-heavy work finishes.
        """
        if entity is not None:
            self.db.expunge(entity)
        if self.db.in_transaction():
            await self.db.rollback()
        return entity

    async def find_by_email(self, email: str) -> Optional[User]:
        """Find a user by email address."""
        result = await self.db.execute(select(User).where(User.email == email))
        return await self._detach_and_release(result.scalar_one_or_none())

    async def find_by_username(self, username: str) -> Optional[User]:
        """Find a user by username."""
        result = await self.db.execute(select(User).where(User.username == username))
        return await self._detach_and_release(result.scalar_one_or_none())

    async def find_by_id(self, user_id: UUID) -> Optional[User]:
        """Find a user by their UUID."""
        result = await self.db.execute(select(User).where(User.id == user_id))
        return await self._detach_and_release(result.scalar_one_or_none())

    async def create(self, user: User) -> User:
        """Insert a new user into the database."""
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_user(self, user_id: UUID, **kwargs) -> Optional[User]:
        """Update fields of an existing user."""
        await self.db.execute(
            update(User).where(User.id == user_id).values(**kwargs, updated_at=datetime.utcnow())
        )
        await self.db.commit()
        return await self.find_by_id(user_id)

    # ── Session (refresh token) methods ──────────────────────

    async def create_session(self, session: Session) -> Session:
        """Store a new refresh token session."""
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def find_session_by_token(self, refresh_token: str) -> Optional[Session]:
        """Look up a session by its refresh token string."""
        result = await self.db.execute(
            select(Session).where(
                Session.refresh_token == refresh_token,
                Session.is_revoked == False,  # noqa: E712
            )
        )
        return await self._detach_and_release(result.scalar_one_or_none())

    async def revoke_session(self, session_id: UUID) -> None:
        """Mark a session as revoked (logout)."""
        await self.db.execute(
            update(Session).where(Session.id == session_id).values(is_revoked=True)
        )
        await self.db.commit()

    async def revoke_all_user_sessions(self, user_id: UUID) -> None:
        """Revoke all sessions for a user (force logout everywhere)."""
        await self.db.execute(
            update(Session).where(Session.user_id == user_id).values(is_revoked=True)
        )
        await self.db.commit()
