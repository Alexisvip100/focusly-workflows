import logging

import jwt
from fastapi import APIRouter, Response, Request, HTTPException, Depends
from typing import Any, Literal
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.routes.common import get_current_user_id
from app.modules.auth.services.auth_service import AuthService
from app.modules.auth.tokens import REFRESH, session_user_id
from app.routes import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Sign-in attempts per client. Generous for people (a typo, a retry), tight
# for scripts: a magic link costs an email from our domain each time.
GOOGLE_LOGIN_LIMIT = (20, 10 * 60)  # per IP, 10 min
MAGIC_LINK_PER_EMAIL = (3, 15 * 60)  # per address, 15 min
MAGIC_LINK_PER_IP = (10, 60 * 60)  # per IP, 1 hour
MAGIC_VERIFY_PER_IP = (20, 15 * 60)  # per IP, 15 min


class GoogleLoginBody(BaseModel):
    code: str


class MagicLinkBody(BaseModel):
    email: EmailStr
    fullName: str | None = Field(default=None, max_length=120)


class VerifyMagicLinkBody(BaseModel):
    token: str


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


def set_auth_cookies(response: Response, result: dict[str, Any]):
    is_secure = settings.IS_PRODUCTION
    samesite_val: Literal["none", "lax"] = "none" if settings.IS_PRODUCTION else "lax"
    response.set_cookie(
        key="access_token",
        value=result["access_token"],
        httponly=True,
        secure=is_secure,
        samesite=samesite_val,
        max_age=15 * 60,
    )
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=True,
        secure=is_secure,
        samesite=samesite_val,
        max_age=7 * 24 * 60 * 60,
    )


@router.post("/google")
async def google_login(
    request: Request,
    body: GoogleLoginBody,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
):
    await rate_limit.enforce(
        "google-login", rate_limit.client_ip(request), *GOOGLE_LOGIN_LIMIT
    )
    try:
        origin = request.headers.get("origin")
        result = await auth_service.validate_google_token(
            body.code, redirect_uri=origin
        )
        set_auth_cookies(response, result)

        return {"user": result["user"]}
    except ValueError:
        # The reason (Google's own error text included) goes to the logs
        logger.warning("Google sign-in refused", exc_info=True)
        raise HTTPException(
            status_code=401, detail="No pudimos iniciar sesión con Google."
        )
    except Exception:
        logger.exception("Google sign-in failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        # Also try to check header just in case
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            refresh_token = auth_header.split(" ")[1]

    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    # The user identity MUST come from the verified token, never from the
    # request body — trusting a client-supplied userId here let anyone with
    # any non-empty refresh_token cookie mint fresh session cookies for an
    # arbitrary account just by naming its id.
    # Only a refresh token: a leaked access token mustn't buy a new week
    try:
        user_id = session_user_id(refresh_token, REFRESH)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    try:
        user = await auth_service.refresh_session(user_id)
        result = auth_service.generate_jwt(user)
        set_auth_cookies(response, result)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/google/refresh")
async def refresh_google_token(
    current_user_id: str = Depends(get_current_user_id),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        return await auth_service.refresh_google_access_token(current_user_id)
    except ValueError:
        logger.warning("Google token refresh refused", exc_info=True)
        raise HTTPException(
            status_code=400, detail="Vuelve a conectar Google Calendar."
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


def clear_auth_cookies(response: Response):
    samesite_val: Literal["none", "lax"] = "none" if settings.IS_PRODUCTION else "lax"
    response.delete_cookie(
        key="access_token", secure=True, httponly=True, samesite=samesite_val
    )
    response.delete_cookie(
        key="refresh_token", secure=True, httponly=True, samesite=samesite_val
    )


@router.post("/logout")
async def logout(response: Response):
    clear_auth_cookies(response)
    return {"message": "Logged out successfully"}


@router.post("/magic-link")
async def request_magic_link(
    request: Request,
    body: MagicLinkBody,
    auth_service: AuthService = Depends(get_auth_service),
):
    await rate_limit.enforce(
        "magic-link-ip", rate_limit.client_ip(request), *MAGIC_LINK_PER_IP
    )
    await rate_limit.enforce("magic-link-email", body.email, *MAGIC_LINK_PER_EMAIL)
    try:
        token = auth_service.generate_magic_link_token(body.email, body.fullName)
        sent = await auth_service.send_magic_link(body.email, token)
    except Exception:
        logger.exception("Magic link request failed")
        raise HTTPException(status_code=500, detail="Internal server error")
    if not sent:
        # Say so: "sent" for an email that never left had people waiting
        # for nothing.
        raise HTTPException(
            status_code=503,
            detail="No pudimos enviar el correo. Inténtalo de nuevo o entra con Google.",
        )
    return {"success": True, "message": "Magic link sent successfully"}


@router.post("/magic-link/verify")
async def verify_magic_link(
    request: Request,
    body: VerifyMagicLinkBody,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
):
    await rate_limit.enforce(
        "magic-verify", rate_limit.client_ip(request), *MAGIC_VERIFY_PER_IP
    )
    try:
        result = await auth_service.verify_magic_link_token(body.token)
        set_auth_cookies(response, result)
        return {"user": result["user"]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")
