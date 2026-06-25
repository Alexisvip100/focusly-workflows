import strawberry

from app.graphql import types
from app.services.auth.auth_service import AuthService


@strawberry.type
class AuthMutation:
    @strawberry.mutation
    async def google_login(self, info, code: str) -> types.AuthResponse:
        db = info.context["db"]
        request = info.context.get("request")
        origin = request.headers.get("origin") if request else None
        auth_service = AuthService(db)
        try:
            result = await auth_service.validate_google_token(code, redirect_uri=origin)

            # Map user
            u = result["user"]
            settings_dict = u.get("settings")
            u_settings = None
            if isinstance(settings_dict, dict):
                work_config = settings_dict.get("workHoursConfig") or {}
                u_settings = types.UserSettings(
                    focus_duration_pref=settings_dict.get("focusDurationPref"),
                    break_duration_pref=settings_dict.get("breakDurationPref"),
                    notifications_enabled=settings_dict.get("notificationsEnabled"),
                )

            user_obj = types.User(
                id=strawberry.ID(u["id"]),
                email=u["email"],
                name=u.get("name"),
                picture=u.get("picture"),
                role=u.get("role"),
                auth_provider=u.get("authProvider"),
                google_refresh_token=u.get("googleRefreshToken"),
                subscription_status=u.get("subscriptionStatus", "free"),
                settings=u_settings,
                bio=u.get("bio"),
            )
            return types.AuthResponse(
                access_token=result["access_token"],
                user=user_obj,
                google_access_token=result.get("google_access_token"),
            )
        except Exception as e:
            print("GraphQL googleLogin error:", e)
            raise Exception(f"Google login failed: {str(e)}")
