"""API-key and short-lived bearer-token authentication utilities."""

import base64
import hashlib
import hmac
import json
import time

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(subject: str, settings: Settings) -> tuple[str, int]:
    """Create an HS256 JWT without adding a heavyweight auth dependency."""
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET must be configured before token auth can be used")
    expires_in = settings.jwt_expiry_minutes * 60
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps(
            {"sub": subject, "iat": int(time.time()), "exp": int(time.time()) + expires_in},
            separators=(",", ":"),
        ).encode()
    )
    unsigned = f"{header}.{payload}"
    signature = _b64url(
        hmac.new(settings.jwt_secret.encode(), unsigned.encode(), hashlib.sha256).digest()
    )
    return f"{unsigned}.{signature}", expires_in


def verify_access_token(token: str, settings: Settings) -> str:
    if not settings.jwt_secret:
        raise ValueError("Bearer authentication is not configured")
    try:
        header, payload, signature = token.split(".")
        unsigned = f"{header}.{payload}"
        expected = _b64url(
            hmac.new(settings.jwt_secret.encode(), unsigned.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid signature")
        claims = json.loads(_b64decode(payload))
        if int(claims["exp"]) <= int(time.time()):
            raise ValueError("Token expired")
        return str(claims["sub"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid or expired token") from exc


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> str | None:
    """
    Verify the API key if one is configured.
    If no API key is set in config, all requests are allowed (dev mode).
    """
    if not settings.api_key:
        # No API key configured — open access (development mode)
        return None

    if not api_key or api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key


async def verify_auth(
    api_key: str | None = Security(api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> str | None:
    """Accept API keys or bearer JWTs; stay open only in unconfigured local development."""
    auth_configured = bool(
        settings.api_key
        or (settings.auth_username and settings.auth_password and settings.jwt_secret)
    )
    if not auth_configured:
        return None
    if settings.api_key and api_key and hmac.compare_digest(api_key, settings.api_key):
        return "api_key"
    if bearer and bearer.scheme.lower() == "bearer":
        try:
            return verify_access_token(bearer.credentials, settings)
        except ValueError:
            pass
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
