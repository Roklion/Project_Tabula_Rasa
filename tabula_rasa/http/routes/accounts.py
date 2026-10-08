from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ..context import RequestContext, resolve_context
from ..errors import ERROR_RESPONSES, TransportError
from ..baselines import required_baseline
from ..models.accounts import Account, AccountCreate, AccountList, AccountUpdate, account_response
from ..models.mutations import ProtectedMutation

router = APIRouter(prefix="/api/v1/entities/{entity_id}/accounts", tags=["Accounts"], responses=ERROR_RESPONSES)
Context = Annotated[RequestContext, Depends(resolve_context)]


@router.get("", response_model=AccountList, operation_id="list_accounts")
def list_accounts(entity_id: str, request: Request, context: Context, active_only: bool = True):
    runtime = request.app.state.runtime
    with runtime.operation():
        service = runtime.services(context).accounts
        if service is None:
            raise TransportError("unavailable")
        return AccountList(items=[account_response(row) for row in service.list(active_only=active_only)])


@router.post("", response_model=Account, status_code=201, operation_id="create_account")
def create_account(entity_id: str, body: AccountCreate, request: Request, context: Context):
    runtime = request.app.state.runtime
    with runtime.operation():
        service = runtime.services(context).accounts
        if service is None:
            raise TransportError("unavailable")
        return account_response(service.create(
            body.name, body.type, body.opening_balance,
            classification=body.classification, parent_id=body.parent_id,
        ))


@router.patch("/{record_id}", response_model=Account, operation_id="update_account")
def update_account(entity_id: str, record_id: str, body: AccountUpdate, request: Request, context: Context):
    expected = required_baseline(body.baseline)
    runtime = request.app.state.runtime
    with runtime.operation():
        service = runtime.services(context).accounts
        if service is None:
            raise TransportError("unavailable")
        return account_response(service.update(record_id, expected=expected, **body.changes.model_dump(exclude_unset=True)))


@router.post("/{record_id}/deactivate", response_model=Account, operation_id="deactivate_account")
def deactivate_account(entity_id: str, record_id: str, body: ProtectedMutation, request: Request, context: Context):
    expected = required_baseline(body.baseline)
    runtime = request.app.state.runtime
    with runtime.operation():
        service = runtime.services(context).accounts
        if service is None:
            raise TransportError("unavailable")
        return account_response(service.deactivate(record_id, expected=expected))
