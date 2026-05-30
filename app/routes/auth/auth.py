from fastapi import APIRouter, Response, Request, HTTPException, Depends, Body
from typing import Dict, Any, Optional
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.services.auth.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginBody(BaseModel):
    token: str
    fullName: str

class GoogleLoginBody(BaseModel):
    code: str

class RefreshBody(BaseModel):
    userId: str

class GoogleRefreshBody(BaseModel):
    userId: str

class MagicLinkBody(BaseModel):
    email: str
    fullName: Optional[str] = None

class VerifyMagicLinkBody(BaseModel):
    token: str

def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)

def set_auth_cookies(response: Response, result: Dict[str, Any]):
    is_secure = settings.IS_PRODUCTION
    response.set_cookie(
        key="access_token",
        value=result["access_token"],
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=15 * 60
    )
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=7 * 24 * 60 * 60
    )

@router.post("/google")
async def google_login(
    request: Request,
    body: GoogleLoginBody,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    try:
        origin = request.headers.get("origin")
        result = await auth_service.validate_google_token(body.code, redirect_uri=origin)
        set_auth_cookies(response, result)
        
        return {"user": result["user"]}
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        print("Google login error:", e)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/login")
async def firebase_login(
    body: LoginBody,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    try:
        result = await auth_service.validate_firebase_token(body.token, body.fullName)
        set_auth_cookies(response, result)
        return {"user": result["user"]}
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        print("Firebase login error:", e)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/refresh")
async def refresh(
    body: RefreshBody,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        # Also try to check header just in case
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            refresh_token = auth_header.split(" ")[1]

    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    try:
        user = await auth_service.refresh_session(body.userId)
        result = auth_service.generate_jwt(user)
        set_auth_cookies(response, result)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/google/refresh")
async def refresh_google_token(
    body: GoogleRefreshBody,
    auth_service: AuthService = Depends(get_auth_service)
):
    try:
        return await auth_service.refresh_google_access_token(body.userId)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token", secure=True, httponly=True, samesite="lax")
    response.delete_cookie(key="refresh_token", secure=True, httponly=True, samesite="lax")
    return {"message": "Logged out successfully"}

@router.post("/magic-link")
async def request_magic_link(
    body: MagicLinkBody,
    auth_service: AuthService = Depends(get_auth_service)
):
    try:
        token = auth_service.generate_magic_link_token(body.email, body.fullName)
        await auth_service.send_magic_link(body.email, token)
        return {"success": True, "message": "Magic link sent successfully"}
    except Exception as e:
        print("Magic link request error:", e)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/magic-link/verify")
async def verify_magic_link(
    body: VerifyMagicLinkBody,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    try:
        result = await auth_service.verify_magic_link_token(body.token)
        set_auth_cookies(response, result)
        return {"user": result["user"]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print("Magic link verification error:", e)
        raise HTTPException(status_code=500, detail="Internal server error")
