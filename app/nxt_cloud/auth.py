from __future__ import annotations

import hmac
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Protocol

from app.nxt_cloud.config import CloudConfig


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    assurance_level: str
    auth_mode: str


class TokenVerifier(Protocol):
    def verify(self, token: str) -> dict: ...


class SupabaseJwtVerifier:
    """Verifies Supabase JWTs with JWKS. Import is lazy so local unit tests need no PyJWT."""

    def __init__(self, issuer: str, audience: str, jwks_url: str) -> None:
        if not issuer or not audience or not jwks_url:
            raise ValueError("JWT issuer, audience and JWKS URL are required")
        try:
            import jwt
        except ImportError as exc:
            raise RuntimeError("PyJWT[crypto] is required for cloud JWT verification") from exc
        self._jwt = jwt
        self._issuer = issuer
        self._audience = audience
        self._client = jwt.PyJWKClient(jwks_url, cache_keys=True)

    def verify(self, token: str) -> dict:
        key = self._client.get_signing_key_from_jwt(token).key
        return self._jwt.decode(
            token,
            key,
            algorithms=["ES256", "RS256"],
            audience=self._audience,
            issuer=self._issuer,
            options={"require": ["exp", "iat", "sub"]},
        )


def _cookie(environ: dict, name: str) -> str:
    parsed = SimpleCookie()
    parsed.load(environ.get("HTTP_COOKIE", ""))
    morsel = parsed.get(name)
    return morsel.value if morsel else ""


def authenticate(environ: dict, verifier: TokenVerifier, config: CloudConfig) -> Principal:
    authorization = environ.get("HTTP_AUTHORIZATION", "")
    auth_mode = "bearer"
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    else:
        token = _cookie(environ, "__Host-nxt_session")
        auth_mode = "cookie"
    if not token:
        raise AuthError("authentication required")
    try:
        claims = verifier.verify(token)
    except Exception as exc:
        raise AuthError("invalid authentication token") from exc
    user_id = str(claims.get("sub", ""))
    email = str(claims.get("email", "")).lower()
    aal = str(claims.get("aal", ""))
    if not user_id or aal not in {"aal1", "aal2"}:
        raise AuthError("password-authenticated assurance level aal1 or higher is required")
    if config.owner_user_ids and user_id not in config.owner_user_ids:
        raise AuthError("user is not in the owner allowlist")
    if config.owner_emails and email not in config.owner_emails:
        raise AuthError("email is not in the owner allowlist")
    if not config.owner_user_ids and not config.owner_emails:
        raise AuthError("owner allowlist is empty")
    return Principal(user_id, email, aal, auth_mode)


def enforce_origin(environ: dict, config: CloudConfig) -> None:
    origin = environ.get("HTTP_ORIGIN", "")
    if origin and origin not in config.allowed_origins:
        raise AuthError("origin is not allowed")


def enforce_csrf(environ: dict, principal: Principal) -> None:
    if principal.auth_mode != "cookie":
        return
    cookie_token = _cookie(environ, "nxt_csrf")
    header_token = environ.get("HTTP_X_CSRF_TOKEN", "")
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise AuthError("CSRF token mismatch")
