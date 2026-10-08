"""Allowlisted errors only: never return/log provider or submitted text."""

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from tabula_rasa.errors import (
    StorageConflictError, StorageError, StorageNotFoundError, StorageValidationError,
)
from .models.common import ErrorCode, ErrorDetail, ErrorEnvelope, FieldError


ERRORS = {
    "validation": (422, "Check the submitted fields."),
    "not_found": (404, "The requested resource was not found."),
    "conflict": (409, "The operation conflicts with the current record."),
    "duplicate": (409, "A matching record already exists."),
    "reference": (422, "A referenced record is unavailable or still in use."),
    "invariant": (422, "The operation violates a bookkeeping rule."),
    "required": (422, "A required value is missing."),
    "baseline_required": (422, "Reload the record before submitting changes."),
    "baseline_invalid": (422, "The loaded record baseline is invalid. Reload the record."),
    "stale": (409, "The record changed since it was loaded. Review the latest record."),
    "concurrent_write": (409, "Another operation changed the record. Review before retrying."),
    "unauthorized": (401, "Sign in to continue."),
    "forbidden": (403, "You do not have access to this operation."),
    "unavailable": (503, "The service is unavailable. Check the record before retrying a save."),
    "unexpected": (500, "The operation could not be completed."),
    "method_not_allowed": (405, "This method is not supported."),
}


class TransportError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def error_response(request, code, *, fields=None):
    if code not in ERRORS:
        code = "unexpected"
    status, message = ERRORS[code]
    request.state.failure_code = code
    envelope = ErrorEnvelope(
        error=ErrorDetail(code=ErrorCode(code), message=message, fields=fields),
        request_id=request.state.request_id,
    )
    return JSONResponse(envelope.model_dump(mode="json", exclude_none=True), status_code=status)


def failure_code(error):
    if isinstance(error, TransportError):
        return error.code
    if isinstance(error, StorageNotFoundError):
        return "not_found"
    if isinstance(error, StorageConflictError):
        return error.code if error.code in {"duplicate", "stale", "concurrent_write"} else "conflict"
    if isinstance(error, StorageValidationError):
        return error.code if error.code in {
            "reference", "invariant", "required", "baseline_required", "baseline_invalid",
        } else "validation"
    if isinstance(error, StorageError):
        return "unavailable"
    # Infrastructure exceptions are translated at the composition boundary.
    return "unexpected"


async def handle_error(request, error):
    return error_response(request, failure_code(error))


async def handle_validation(request, error: RequestValidationError):
    # Locations can contain client-supplied keys (extra fields): allow only
    # declared transport field names. Never echo input, context, or raw messages.
    allowed = {"name", "type", "opening_balance", "classification", "parent_id", "active_only"}
    fields = [
        FieldError(field=str(item["loc"][-1]), code="invalid", message="Check this value.")
        for item in error.errors()
        if item.get("loc") and item["loc"][-1] in allowed
    ]
    return error_response(request, "validation", fields=fields or None)


async def handle_http_error(request, error: HTTPException):
    code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}.get(
        error.status_code, "unexpected",
    )
    return error_response(request, code)


ERROR_RESPONSES = {
    status: {"model": ErrorEnvelope, "description": description}
    for status, description in [
        (401, "Identity required"), (403, "Operation denied"), (404, "Resource not found"),
        (409, "Duplicate or concurrent change"), (422, "Transport or domain validation"),
        (503, "Dependency unavailable"), (500, "Unexpected failure"),
    ]
}
