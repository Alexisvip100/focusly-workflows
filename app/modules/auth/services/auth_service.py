import time
from typing import Dict, Any, Optional
import jwt
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.models import User


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def validate_google_token(self, code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        try:
            # Exchange code for Google tokens
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "code": code,
                        "client_id": settings.GOOGLE_CLIENT_ID,
                        "client_secret": settings.GOOGLE_CLIENT_SECRET,
                        "redirect_uri": redirect_uri or settings.GOOGLE_REDIRECT_URI,
                        "grant_type": "authorization_code"
                    }
                )
                if res.status_code != 200:
                    raise ValueError(f"Failed to exchange Google OAuth code: {res.text}")
                tokens = res.json()
                access_token = tokens.get("access_token")

                # Get user info
                user_res = await client.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                if user_res.status_code != 200:
                    raise ValueError("Failed to get Google user info")
                user_info = user_res.json()

            email = user_info.get("email")
            name = user_info.get("name")
            picture = user_info.get("picture")

            if not email:
                raise ValueError("Email not found in Google user info")

            result = await self.db.execute(select(User).where(User.email == email))
            user = result.scalars().first()

            refresh_token = tokens.get("refresh_token")

            if not user:
                import uuid
                user = User(
                    id=str(uuid.uuid4()),
                    email=email,
                    name=name,
                    picture=picture,
                    authProvider="google",
                    role="user",
                    subscriptionStatus="free",
                    googleRefreshToken=refresh_token
                )
                self.db.add(user)
                await self.db.commit()
                await self.db.refresh(user)
            elif refresh_token:
                user.googleRefreshToken = refresh_token
                await self.db.commit()
                await self.db.refresh(user)

            jwt_data = self.generate_jwt(user)
            jwt_data["google_access_token"] = access_token
            return jwt_data
        except Exception as e:
            raise ValueError(f"Invalid Google OAuth Token: {str(e)}")

    async def refresh_google_access_token(self, user_id: str) -> Dict[str, Any]:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()

        if not user or not user.googleRefreshToken:
            raise ValueError("No valid refresh token found for this user")

        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "refresh_token": user.googleRefreshToken,
                    "grant_type": "refresh_token"
                }
            )
            if res.status_code != 200:
                raise ValueError(f"Failed to refresh Google token: {res.text}")
            credentials = res.json()

        return {
            "access_token": credentials.get("access_token"),
            "expiry_date": int(time.time() * 1000) + (credentials.get("expires_in", 3600) * 1000)
        }

    async def refresh_session(self, user_id: str) -> User:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            raise ValueError("User not found")
        return user

    def generate_jwt(self, user: User) -> Dict[str, Any]:
        now = time.time()
        payload = {
            "email": user.email,
            "sub": user.id,
            "role": user.role,
            "iat": int(now),
        }
        
        # Access token: 15 minutes
        access_payload = payload.copy()
        access_payload["exp"] = int(now + 15 * 60)
        access_token = jwt.encode(access_payload, settings.JWT_SECRET, algorithm="HS256")
        
        # Refresh token: 7 days
        refresh_payload = payload.copy()
        refresh_payload["exp"] = int(now + 7 * 24 * 60 * 60)
        refresh_token = jwt.encode(refresh_payload, settings.JWT_SECRET, algorithm="HS256")

        # Map to dict matches IUser interface
        user_dict = {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "picture": user.picture,
            "role": user.role,
            "bio": user.bio,
            "authProvider": user.authProvider,
            "subscriptionStatus": user.subscriptionStatus,
            "settings": user.settings,
            "fcmToken": user.fcmToken,
            "createdAt": user.createdAt.isoformat() if user.createdAt else None,
            "updatedAt": user.updatedAt.isoformat() if user.updatedAt else None,
            "googleRefreshToken": user.googleRefreshToken,
        }

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user_dict
        }

    def generate_magic_link_token(self, email: str, full_name: Optional[str] = None) -> str:
        now = time.time()
        payload = {
            "email": email.strip().lower(),
            "fullName": full_name,
            "purpose": "magic-link",
            "iat": int(now),
            "exp": int(now + 15 * 60)  # 15 minutes
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

    async def send_magic_link(self, email: str, token: str) -> None:
        magic_link = f"http://localhost:5173/login?token={token}"
        
        if settings.RESEND_API_KEY:
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(
                        "https://api.resend.com/emails",
                        headers={
                            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                            "Content-Type": "application/json"
                       },
                       json={
                           "from": "Focusly <onboarding@resend.dev>",
                           "to": email,
                           "subject": "Your Focusly Magic Link",
                           "html": f"""
                           <div style="font-family: sans-serif; padding: 20px; max-width: 600px; margin: 0 auto; border: 1px solid #eee; border-radius: 10px;">
                               <h2 style="color: #137fec;">Welcome to Focusly</h2>
                               <p>Click the button below to log in to your account. This link will expire in 15 minutes.</p>
                               <div style="margin: 30px 0;">
                                   <a href="{magic_link}" style="background-color: #137fec; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">Log in to Focusly</a>
                               </div>
                               <p style="color: #666; font-size: 12px;">If you did not request this email, you can safely ignore it.</p>
                               <hr style="border: 0; border-top: 1px solid #eee;" />
                               <p style="color: #999; font-size: 10px;">If the button doesn't work, copy and paste this URL into your browser: <br/> {magic_link}</p>
                           </div>
                           """
                       }
                    )
                    if response.status_code in (200, 201):
                        return
                except Exception:
                    pass

    async def verify_magic_link_token(self, token: str) -> Dict[str, Any]:
        try:
            decoded = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise ValueError("Magic Link has expired")
        except jwt.InvalidTokenError:
            raise ValueError("Invalid Magic Link token")

        if decoded.get("purpose") != "magic-link":
            raise ValueError("Invalid token purpose")

        email = decoded.get("email")
        full_name = decoded.get("fullName")

        if not email:
            raise ValueError("Email not found in token")

        # Find or create user in Postgres
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

        if not user:
            import uuid
            user = User(
                id=str(uuid.uuid4()),
                email=email,
                name=full_name or email.split("@")[0].title(),
                authProvider="email",
                role="user",
                subscriptionStatus="free"
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)

        return self.generate_jwt(user)
