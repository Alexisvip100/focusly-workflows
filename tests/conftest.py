import sys
import typing
import sqlalchemy.util.typing

# Fix for SQLAlchemy 2.0 type annotation de-stringification on Python 3.14+
if sys.version_info >= (3, 14):
    sqlalchemy.util.typing.make_union_type = lambda *types: typing.Union[types]  # type: ignore

import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def _no_canvas_storage(monkeypatch):
    """Deleting a canvas also clears its images from object storage; tests
    must never reach a real bucket (an unreachable one stalls on retries)."""
    from app.modules.canvas.services import canvas_files

    monkeypatch.setattr(canvas_files, "s3_client", MagicMock())
