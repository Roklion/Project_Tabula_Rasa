from typing import Literal
from pydantic import Field
from .common import DTO


class ConnectionInfo(DTO):
    provider: Literal['google_drive'] = 'google_drive'
    status: Literal['not_configured', 'pending', 'connected', 'disconnected', 'reconnect_required']
    revision: int
    self_service_available: bool = False
    authorization_status: Literal['connecting', 'failed'] | None = None
    authorized_account: str | None = None


class ConnectionChange(DTO):
    revision: int = Field(ge=1)
    connect: bool


class ConnectionStart(DTO):
    revision: int = Field(ge=0)


class ConnectionAuthorization(DTO):
    authorization_url: str
