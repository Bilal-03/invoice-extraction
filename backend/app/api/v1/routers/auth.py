"""Authentication endpoint for interactive dashboard clients."""

import hmac

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.domain.schemas import TokenRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def issue_token(request: TokenRequest, settings: Settings = Depends(get_settings)):
    if not settings.auth_username or not settings.auth_password or not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password authentication is not configured",
        )
    valid_user = hmac.compare_digest(request.username, settings.auth_username)
    valid_password = hmac.compare_digest(request.password, settings.auth_password)
    if not (valid_user and valid_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token, expires_in = create_access_token(request.username, settings)
    return TokenResponse(access_token=token, expires_in=expires_in)
