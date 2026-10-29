from dataclasses import asdict, dataclass
from typing import Any

from graphql import GraphQLError

# What each plan allows. The frontend shows the same numbers (it reads them
# from GET /api/billing/status), so they only live here.

FREE = "free"
PRO = "pro"

# AI (Lumina's chat, the planners, Insights' analysis; the editor assistant
# is Pro only). Every use costs Gemini tokens, so both plans have a limit:
# - Free: this many messages a calendar month (UTC), to try Lumina and come
#   back to it. They renew on the 1st.
FREE_AI_MESSAGE_LIMIT = 10
# - Pro, fair use: this many a day (UTC), far above what anyone uses by
#   hand (10–30), to stop scripts and runaway use.
PRO_DAILY_AI_LIMIT = 150
# - Pro, cost: past this much Gemini spend in a month (about 45% of the $18
#   Pro price) Lumina keeps answering, with the cheaper model.
PRO_MONTHLY_AI_COST_CAP_USD = 8.0

# Gemini prices, USD per million tokens: input, cached input, output (thinking
# included). https://ai.google.dev/gemini-api/docs/pricing. A model not listed
# is costed as the dearest one, so the caps never under-count.
AI_PRICES_PER_MILLION: dict[str, tuple[float, float, float]] = {
    "gemini-3.5-flash-lite": (0.30, 0.03, 2.50),
    "gemini-2.5-flash": (0.30, 0.03, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.01, 0.40),
}
_DEAREST_PRICE = max(AI_PRICES_PER_MILLION.values(), key=lambda p: p[2])


def ai_cost_micros(usage: dict[str, Any] | None) -> int:
    """What one reply cost, in millionths of a dollar, from the token
    counts focusly-ai reports (input, cached, output, thoughts)."""
    if not usage:
        return 0
    price_in, price_cached, price_out = AI_PRICES_PER_MILLION.get(
        str(usage.get("model") or ""), _DEAREST_PRICE
    )
    tokens = lambda key: max(0, int(usage.get(key) or 0))  # noqa: E731
    cached = min(tokens("cached"), tokens("input"))
    # A dollar per million tokens is a millionth of a dollar per token
    return round(
        (tokens("input") - cached) * price_in
        + cached * price_cached
        + (tokens("output") + tokens("thoughts")) * price_out
    )

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
