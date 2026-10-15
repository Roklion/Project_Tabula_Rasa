from typing import Literal
from pydantic import Field
from .common import DTO


class ConnectionInfo(DTO):
    provider: Literal['google_drive'] = 'google_drive'
    status: Literal['not_configured', 'pending', 'connected', 'disconnected', 'reconnect_required']
    revision: int


class ConnectionChange(DTO):
    revision: int = Field(ge=1)
    connect: bool
