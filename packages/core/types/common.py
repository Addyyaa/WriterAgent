from __future__ import annotations

from datetime import datetime
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonDict: TypeAlias = dict[str, JsonValue]

ProjectId: TypeAlias = str | int
SourceId: TypeAlias = str | int
TimestampLike: TypeAlias = str | datetime
