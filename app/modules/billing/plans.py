from dataclasses import asdict, dataclass
from typing import Any

from graphql import GraphQLError

# What each plan allows. The frontend shows the same numbers (it reads them
# from GET /api/billing/status), so they only live here.

FREE = "free"
PRO = "pro"

# Free plan: this many AI chat messages in total, to try Lumina. The editor
# assistant is Pro only.
FREE_AI_MESSAGE_LIMIT = 5

# Canvases (drawings in documents). Free is enough to try them; Pro lifts the
# count and makes room for bigger drawings and photos. Sizes are what one
# canvas may hold: its scene (shapes and text, saved whole on every autosave)
# and each image pasted into it (stored apart, in the bucket).
MB = 1024 * 1024


@dataclass(frozen=True)
class CanvasLimits:
    # None: no limit
    max_canvases: int | None
    max_scene_bytes: int
    max_image_bytes: int
    max_images_per_canvas: int

    def as_dict(self) -> dict[str, int | None]:
        return asdict(self)


FREE_CANVAS_LIMITS = CanvasLimits(
    max_canvases=3,
    max_scene_bytes=1 * MB,
    max_image_bytes=2 * MB,
    max_images_per_canvas=10,
)
PRO_CANVAS_LIMITS = CanvasLimits(
    max_canvases=None,
    max_scene_bytes=5 * MB,
    max_image_bytes=10 * MB,
    max_images_per_canvas=100,
)

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


def canvas_limits(user: Any) -> CanvasLimits:
    return PRO_CANVAS_LIMITS if is_pro(user) else FREE_CANVAS_LIMITS


class PlanLimitError(GraphQLError):
    """A GraphQL request the user's plan doesn't cover. Clients read
    extensions.code, like the REST endpoints' 402 detail.code, to offer Pro."""

    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message, extensions={"code": code, **details})


def is_editor_request(
    *, document_context: str | None, persist: bool, workspace_id: str | None
) -> bool:
    """The workspace editor's assistant or its one-shot rewrites (not the chat)."""
    return document_context is not None or not persist or bool(workspace_id)
