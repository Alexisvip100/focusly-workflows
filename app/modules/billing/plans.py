from typing import Any

# What each plan allows. The frontend shows the same numbers (it reads them
# from GET /api/billing/status), so they only live here.

FREE = "free"
PRO = "pro"

# Free plan: this many AI chat messages in total, to try Lumina. The editor
# assistant is Pro only.
FREE_AI_MESSAGE_LIMIT = 5

# Stripe subscription states that keep Pro access. past_due: Stripe is still
# retrying the card, so the user keeps access meanwhile.
ACCESS_STATUSES = frozenset({"active", "trialing", "past_due"})


def _field(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    try:
        return obj[key]
    except (KeyError, TypeError):
        return None


def grants_access(subscription: Any) -> bool:
    """Whether a Stripe subscription makes its user Pro. A free trial only
    does once the card is on file: the trial starts ("trialing") before the
    browser has even shown the card form."""
    status = _field(subscription, "status")
    if status not in ACCESS_STATUSES:
        return False
    return status != "trialing" or bool(_field(subscription, "default_payment_method"))


def is_pro(user: Any) -> bool:
    return (getattr(user, "subscriptionStatus", None) or FREE) == PRO


def is_editor_request(
    *, document_context: str | None, persist: bool, workspace_id: str | None
) -> bool:
    """The workspace editor's assistant or its one-shot rewrites (not the chat)."""
    return document_context is not None or not persist or bool(workspace_id)
