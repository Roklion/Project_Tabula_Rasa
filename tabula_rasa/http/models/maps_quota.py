from typing import Literal

from pydantic import Field

from .common import DTO


class MapsQuotaGroup(DTO):
    title: Literal['Routes API', 'Places API (New)']
    rows: list[str]


class MapsQuotaStatus(DTO):
    status: Literal['not_loaded', 'unconfigured', 'ready', 'error']
    message: str | None = None
    services: list[MapsQuotaGroup] = Field(default_factory=list)
    cache_remaining_seconds: float = 0


class MapsQuotaRequest(DTO):
    refresh: bool = False
