"""Amazon Cognito JWT verification (ID or access token from the Hosted UI / SDK)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from insightly.config import get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass
class User:
    id: str
    role: str
    email: str | None = None


@lru_cache
def _jwks() -> jwt.PyJWKClient:
    s = get_settings()
    url = f"https://cognito-idp.{s.aws_region}.amazonaws.com/{s.cognito_user_pool_id}/.well-known/jwks.json"
    return jwt.PyJWKClient(url, cache_keys=True)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    s = get_settings()
    if s.auth_mode == "disabled":
        return User(id="local-dev", role="analyst")
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        key = _jwks().get_signing_key_from_jwt(creds.credentials).key
        issuer = f"https://cognito-idp.{s.aws_region}.amazonaws.com/{s.cognito_user_pool_id}"
        claims = jwt.decode(
            creds.credentials, key, algorithms=["RS256"], issuer=issuer, options={"verify_aud": False}
        )
        client = claims.get("aud") or claims.get("client_id")
        if client != s.cognito_client_id:
            raise jwt.InvalidTokenError("token issued for another app client")
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}") from e
    groups = claims.get("cognito:groups") or []
    role = "admin" if "admin" in groups else "analyst"
    return User(id=claims["sub"], role=role, email=claims.get("email"))
