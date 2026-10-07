import re
import unicodedata

# Which Gemini model answers a message. Picked from the message itself: asking
# a model to classify cost a call (with thinking) on every message, to save
# less than it spent.

# Tiers, not versions: focusly-ai maps them to the Gemini models it's set up
# with (AI_GEMINI_LIGHT_MODEL / AI_GEMINI_STRONG_MODEL), so a model Google
# retires is changed there.
LIGHT_MODEL = "gemini-flash-lite"
STRONG_MODEL = "gemini-flash"
# What a client may ask for; anything else ("auto", retired ids) is picked here.
SELECTABLE_MODELS = {
    LIGHT_MODEL: LIGHT_MODEL,
    STRONG_MODEL: STRONG_MODEL,
    # Names older versions of the app send.
    "gemini-2.5-flash-lite": LIGHT_MODEL,
    "gemini-2.5-flash": STRONG_MODEL,
}

LONG_MESSAGE_CHARS = 500

# Planning, breaking down or reasoning over several things: worth the
# stronger model. A single quick action ("crea una tarea…") isn't.
_COMPLEX = re.compile(
    r"\b("
    r"planific\w*|planea\w*|plan|organiz\w*|reorganiz\w*|prioriz\w*|"
    r"analiz\w*|analisis|estrategi\w*|resum\w*|compar\w*|semana\w*|"
    r"reprogram\w*|distribu\w*|desglos\w*|divid\w*|proyecto\w*|roadmap|"
    r"investig\w*|optimiz\w*|evalu\w*|explica\w*|por que|"
    r"plans?|planning|organi[sz]\w*|prioriti[sz]\w*|analy[sz]\w*|"
    r"strateg\w*|summari[sz]\w*|compare|week\w*|reschedul\w*|"
    r"break (?:it |this )?down|research|optimi[sz]\w*|evaluat\w*|explain|why"
    r")\b"
)
_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.MULTILINE)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def classify_query(user_query: str, *, has_attachments: bool = False) -> str:
    """'complex' for planning, analysis, long or multi-part requests and
    attached files; 'simple' otherwise."""
    if has_attachments:
        return "complex"
    text = _normalize(user_query)
    if len(text) > LONG_MESSAGE_CHARS:
        return "complex"
    if len(_LIST_ITEM.findall(text)) >= 3:
        return "complex"
    return "complex" if _COMPLEX.search(text) else "simple"


def pick_model(
    requested: str | None, user_query: str, *, has_attachments: bool = False
) -> str:
    """The client's choice when it's one we offer, else by the message."""
    if requested in SELECTABLE_MODELS:
        return SELECTABLE_MODELS[requested]
    complexity = classify_query(user_query, has_attachments=has_attachments)
    return STRONG_MODEL if complexity == "complex" else LIGHT_MODEL
