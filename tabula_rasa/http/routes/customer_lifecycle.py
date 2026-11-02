"""Named, CSRF-protected lifecycle commands, independent of selected ledger."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field

from tabula_rasa.application.identity import IdentityError
from ..errors import ERROR_RESPONSES
from ..models.common import DTO

router = APIRouter(prefix='/api/v1/customer-lifecycle', tags=['Customer lifecycle'], responses=ERROR_RESPONSES)


class LifecycleEvent(DTO):
    action: str
    occurred_at: datetime
    actor_id: str


class LifecycleRecord(DTO):
    id: str
    requester_id: str
    entity_id: str | None
    kind: Literal['business_closure', 'account_closure', 'privacy_erasure']
    state: Literal['pending', 'confirmed', 'cancelled']
    effective_state: str
    version: int
    policy_version: str
    created_at: datetime
    confirmed_at: datetime | None
    recover_until: datetime | None
    events: list[LifecycleEvent]


class LifecycleStatus(DTO):
    policy_version: str
    recovery_days: int
    deletion_available: Literal[False]
    deletion_blockers: list[str]
    last_owned_businesses: list[str]
    requests: list[LifecycleRecord]


class LifecycleRequest(DTO):
    request_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{16,80}$')
    kind: Literal['business_closure', 'account_closure', 'privacy_erasure']
    entity_id: str | None = Field(default=None, min_length=1, max_length=200)


class LifecycleChange(DTO):
    action: Literal['confirm', 'cancel']
    version: int = Field(ge=1)
    export_saved: bool = False


def workflow(request):
    runtime = request.app.state.runtime
    if runtime.identity is None or runtime.lifecycle is None:
        raise IdentityError('forbidden')
    return runtime.lifecycle, runtime.identity.authenticated(request)


@router.get('', response_model=LifecycleStatus, operation_id='customer_lifecycle_status')
def status(request: Request, business_id: str | None = None):
    service, session = workflow(request)
    return service.status(session, business_id)


@router.post('', response_model=LifecycleRecord, operation_id='request_customer_lifecycle')
def request_lifecycle(body: LifecycleRequest, request: Request):
    service, session = workflow(request)
    return service.request(session, body.request_id, body.kind, body.entity_id)


@router.post('/{request_id}', response_model=LifecycleRecord, operation_id='change_customer_lifecycle')
def change_lifecycle(request_id: str, body: LifecycleChange, request: Request):
    service, session = workflow(request)
    return service.change(session, request_id, body.action, body.version, export_saved=body.export_saved)
