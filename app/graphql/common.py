def get_user_id(info) -> str:
    user_id = info.context.get("user_id")
    if not user_id:
        raise Exception("Unauthorized: user is not authenticated")
    return user_id