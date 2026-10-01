from datetime import datetime
from typing import Any

from app.database import safe_attr

# Version of the Terms and Privacy Notice every user must have accepted.
# Bump it to the documents' "Última actualización" date whenever
# focusly-front/src/content/legal/*/{terms,privacy}.md change in a way users
# must re-accept: every user is then asked to accept again on next login.
CURRENT_TERMS_VERSION = "2026-10-01"


def terms_fields(user: Any) -> dict[str, Any]:
    """Terms-acceptance fields included in every user payload sent to clients."""
    accepted_version = safe_attr(user, "termsVersion")
    accepted_at = safe_attr(user, "termsAcceptedAt")
    return {
        "termsVersion": accepted_version,
        "termsAcceptedAt": (
            accepted_at.isoformat() if isinstance(accepted_at, datetime) else accepted_at
        ),
        "needsTermsAcceptance": accepted_version != CURRENT_TERMS_VERSION,
    }
