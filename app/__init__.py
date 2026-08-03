import sys
import typing
import sqlalchemy.util.typing

if sys.version_info >= (3, 14):
    sqlalchemy.util.typing.make_union_type = lambda *types: typing.Union[types]  # type: ignore
