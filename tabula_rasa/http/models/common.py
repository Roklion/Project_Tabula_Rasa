from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_serializer


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorCode(StrEnum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PERIOD_CLOSED = 'period_closed'
    DUPLICATE = "duplicate"
    REFERENCE = "reference"
    INVARIANT = "invariant"
    REQUIRED = "required"
    BASELINE_REQUIRED = "baseline_required"
    BASELINE_INVALID = "baseline_invalid"
    STALE = "stale"
    CONCURRENT_WRITE = "concurrent_write"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    UNAVAILABLE = "unavailable"
    UNEXPECTED = "unexpected"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    REAUTHENTICATION_REQUIRED = 'reauthentication_required'
    INVITATION_INVALID = 'invitation_invalid'
    INVITATION_USED = 'invitation_used'
    INVITATION_EXPIRED = 'invitation_expired'


class FieldError(DTO):
    field: str
    code: str
    message: str


class ErrorDetail(DTO):
    code: ErrorCode
    message: str
    fields: list[FieldError] | None = None


class ErrorEnvelope(DTO):
    error: ErrorDetail
    request_id: str


class Health(DTO):
    status: str


class Version(DTO):
    release: str


class EntityInfo(DTO):
    id: str
    name: str
    organization_id: str | None = None
    organization_name: str | None = None
    role: str | None = None

    @model_serializer(mode='wrap')
    def omit_absent_workspace_claims(self, handler):
        return {key: value for key, value in handler(self).items() if value is not None}


class EntityList(DTO):
    items: list[EntityInfo]


class BusinessInfo(DTO):
    id: str
    name: str
    role: str | None = None


class BusinessList(DTO):
    items: list[BusinessInfo]


class EntitySelection(DTO):
    entity_id: str


class LogoutContext(DTO):
    csrf_token: str


class SessionInfo(DTO):
    state: Literal["ready"] = "ready"
    actor_id: str
    organization_id: str
    entity: EntityInfo
    capabilities: list[str]
    cache_scope: str
    csrf_token: str
    trusted_development: bool


class SetupSessionInfo(DTO):
    state: Literal["needs_setup"] = "needs_setup"
    actor_id: str
    organization_id: None = None
    entity: None = None
    capabilities: list[str] = []
    cache_scope: str
    csrf_token: str
    trusted_development: Literal[False] = False
