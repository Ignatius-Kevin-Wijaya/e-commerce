"""
Auth HTTP handlers — FastAPI route definitions.

LEARNING NOTES:
- Handlers are the "controllers" — they handle HTTP requests/responses.
- They validate input (via Pydantic schemas), call the service layer,
  and format the HTTP response.
- They should NOT contain business logic — that belongs in auth_service.py.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from internal.middleware.jwt_middleware import get_current_user_id
from internal.repository.user_repository import UserRepository
from internal.service.auth_service import AuthService, AuthServiceError

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ── Pydantic request/response schemas ───────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    full_name: Optional[str]
    is_active: bool
    is_admin: bool
    created_at: str

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    message: str


# ── Dependency: build service from DB session ───────────────

async def get_auth_service(request: Request) -> AuthService:
    """Factory that creates AuthService with a DB session from app state."""
    db: AsyncSession = request.state.db
    repo = UserRepository(db)
    return AuthService(repo)


# ── Route handlers ──────────────────────────────────────────

@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
):
    """Register a new user account."""
    try:
        user = await service.register(
            email=body.email,
            username=body.username,
            password=body.password,
            full_name=body.full_name,
        )
        return UserResponse(
            id=str(user.id),
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            is_active=user.is_active,
            is_admin=user.is_admin,
            created_at=user.created_at.isoformat(),
        )
    except AuthServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
):
    """Authenticate and receive JWT tokens."""
    try:
        tokens = await service.login(
            email=body.email,
            password=body.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
        return TokenResponse(**tokens)
    except AuthServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
):
    """Exchange a refresh token for a new access + refresh token pair."""
    try:
        tokens = await service.refresh_access_token(body.refresh_token)
        return TokenResponse(**tokens)
    except AuthServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    body: LogoutRequest,
    service: AuthService = Depends(get_auth_service),
):
    """Logout (revoke the refresh token)."""
    await service.logout(body.refresh_token)
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserResponse)
async def get_me(
    user_id: UUID = Depends(get_current_user_id),
    service: AuthService = Depends(get_auth_service),
):
    """Get the currently authenticated user's profile."""
    try:
        user = await service.get_current_user(user_id)
        return UserResponse(
            id=str(user.id),
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            is_active=user.is_active,
            is_admin=user.is_admin,
            created_at=user.created_at.isoformat(),
        )
    except AuthServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
