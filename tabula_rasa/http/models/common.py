from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorCode(StrEnum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
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


class EntityList(DTO):
    items: list[EntityInfo]


class EntitySelection(DTO):
    entity_id: str


class SessionInfo(DTO):
    actor_id: str
    organization_id: str
    entity: EntityInfo
    capabilities: list[str]
    cache_scope: str
    csrf_token: str
    trusted_development: bool
