"""Internal support API. Independent of selected business and tenant capabilities."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from tabula_rasa.application.support import AdministrativeResult, AuditPage, Diagnostics
from tabula_rasa.application.identity import IdentityError
from ..errors import ERROR_RESPONSES

router = APIRouter(prefix='/api/v1/support/{organization_id}/{business_id}', tags=['support'], responses=ERROR_RESPONSES)

Reason = Literal['incident', 'access_request', 'job_failure', 'migration_failure', 'connection_failure', 'audit_review']


class SupportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: Reason


class AuditRequest(SupportRequest):
    since: datetime | None = None
    until: datetime | None = None
    actor_id: str | None = Field(default=None, max_length=200)
    action: Literal['create', 'update', 'delete'] | None = None
    source: str | None = Field(default=None, max_length=200)
    target_type: str | None = Field(default=None, max_length=200)
    target_id: str | None = Field(default=None, max_length=200)
    batch_id: str | None = Field(default=None, max_length=200)
    operation_id: str | None = Field(default=None, max_length=200)
    after_sequence: int = Field(default=0, ge=0)
    through_sequence: int | None = Field(default=None, ge=0, le=9223372036854775807)
    limit: int = Field(default=100, ge=1, le=100)


class AdminRequest(SupportRequest):
    operation: Literal['revoke_sessions', 'suspend_member', 'suspend_organization']
    target_user_id: str | None = Field(default=None, min_length=1, max_length=200)
    confirm_plan: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')


def invoke(request, organization_id, business_id, body, operation):
    runtime = request.app.state.runtime
    request.state.security_event = 'privileged_denied'
    request.state.security_reason = 'capability'
    identity = runtime.identity
    if identity is None or runtime.support is None:
        raise IdentityError('forbidden')
    with runtime.operation():
        result = getattr(runtime.support, operation)(
            request.cookies.get(identity.session_cookie, ''), organization_id, business_id,
            correlation_id=request.state.request_id, **body.model_dump())
    request.state.security_event = None
    request.state.security_reason = None
    return result


@router.post('/diagnostics', operation_id='support_diagnostics', response_model=Diagnostics)
def diagnostics(request: Request, organization_id: str, business_id: str, body: SupportRequest):
    return invoke(request, organization_id, business_id, body, 'diagnostics')


@router.post('/audit', operation_id='support_audit', response_model=AuditPage)
def audit(request: Request, organization_id: str, business_id: str, body: AuditRequest):
    return invoke(request, organization_id, business_id, body, 'audit')


@router.post('/administration', operation_id='support_administer', response_model=AdministrativeResult)
def administer(request: Request, organization_id: str, business_id: str, body: AdminRequest):
    return invoke(request, organization_id, business_id, body, 'administer')
