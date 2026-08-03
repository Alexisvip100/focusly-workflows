import sys
import typing
import sqlalchemy.util.typing

# Fix for SQLAlchemy 2.0 type annotation de-stringification on Python 3.14+
if sys.version_info >= (3, 14):
    sqlalchemy.util.typing.make_union_type = lambda *types: typing.Union[types]  # type: ignore
