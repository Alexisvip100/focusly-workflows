from typing import Any, Literal

import jwt

from app.config import settings

# A session is two tokens signed with the same secret: a short access token,
# for calling the API, and a long refresh token, only for /auth/refresh to get
# new ones. Each says which it is, so neither can stand in for the other: a
# leaked refresh token can't call the API for a week, and a leaked access
# token can't be turned into a week-long session.
ACCESS: Literal["access"] = "access"
REFRESH: Literal["refresh"] = "refresh"
TokenType = Literal["access", "refresh"]

ACCESS_TOKEN_SECONDS = 15 * 60
REFRESH_TOKEN_SECONDS = 7 * 24 * 60 * 60


def session_claims(token_type: TokenType, base: dict[str, Any], now: float) -> dict[str, Any]:
    lifetime = ACCESS_TOKEN_SECONDS if token_type == ACCESS else REFRESH_TOKEN_SECONDS
    return {**base, "type": token_type, "exp": int(now + lifetime)}


def _token_type(payload: dict[str, Any]) -> str | None:
    if "type" in payload:
        return payload["type"]
    # Issued before tokens said their type (until 7 days after that release
    # they can still turn up): the lifetime tells them apart.
    lifetime = payload.get("exp", 0) - payload.get("iat", 0)
    return ACCESS if 0 < lifetime <= ACCESS_TOKEN_SECONDS else REFRESH


def session_user_id(token: str, token_type: TokenType) -> str:
    """The user a session token of this type belongs to.

    Raises jwt.ExpiredSignatureError for an expired one and
    jwt.InvalidTokenError for anything else that isn't such a token."""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    if _token_type(payload) != token_type:
        raise jwt.InvalidTokenError(f"Not an {token_type} token")
    user_id = payload.get("sub")
    if not user_id:
        raise jwt.InvalidTokenError("Token has no subject")
    return str(user_id)
