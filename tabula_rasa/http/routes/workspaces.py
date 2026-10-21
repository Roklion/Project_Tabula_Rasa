"""Transport-only workspace handlers; named identity without a selected ledger."""

from typing import Annotated

from fastapi import APIRouter, Path, Request, Response
from tabula_rasa.application.workspaces import BOOTSTRAP_ID_PATTERN

from ..errors import ERROR_RESPONSES, TransportError
from ..models.common import ErrorEnvelope
from ..models.workspaces import (
    BusinessCreateRequest, BusinessCreateResult, BootstrapRequest, BootstrapResult, MemberChange, MemberList, InviteRequest,
    InviteIssued, InvitationList, InvitationResponse, InvitationOutcome, OwnershipGrant,
)

router = APIRouter(responses=ERROR_RESPONSES, tags=['Business access'])


def workflow(request):
    runtime = request.app.state.runtime
    if runtime.identity is None:
        raise TransportError('forbidden')
    return runtime.workspaces, runtime.identity.authenticated(request)


@router.post('/api/v1/businesses', response_model=BusinessCreateResult, operation_id='create_business', tags=['Businesses'])
def create_business(body: BusinessCreateRequest, request: Request):
    service, session = workflow(request)
    result = service.create_business(session, body.request_id, body.business_name)
    return BusinessCreateResult(state=result['state'], entity_id=result.get('entity_id'))


@router.get('/api/v1/businesses/creation/{request_id}', response_model=BusinessCreateResult,
            operation_id='business_creation_status', tags=['Businesses'])
def business_creation_status(request_id: Annotated[str, Path(pattern=BOOTSTRAP_ID_PATTERN)], request: Request):
    service, session = workflow(request)
    result = service.bootstrap_status(session, request_id)
    return BusinessCreateResult(state=result['state'], entity_id=result.get('entity_id'))


@router.post('/api/v1/workspaces/bootstrap', response_model=BootstrapResult, operation_id='bootstrap_workspace', deprecated=True)
def bootstrap_workspace(body: BootstrapRequest, request: Request):
    service, session = workflow(request)
    return service.bootstrap(session, body.request_id, body.workspace_name, body.business_name)


@router.get('/api/v1/workspaces/bootstrap/{request_id}', response_model=BootstrapResult, operation_id='bootstrap_status')
def bootstrap_status(request_id: Annotated[str, Path(pattern=BOOTSTRAP_ID_PATTERN)], request: Request):
    service, session = workflow(request)
    return service.bootstrap_status(session, request_id)


@router.post('/api/v1/workspaces/{organization_id}/businesses', response_model=BootstrapResult, operation_id='bootstrap_business', deprecated=True)
def bootstrap_business(organization_id: str, body: BootstrapRequest, request: Request):
    service, session = workflow(request)
    return service.bootstrap(session, body.request_id, body.workspace_name, body.business_name, organization_id)


@router.get('/api/v1/workspaces/{organization_id}/members', response_model=MemberList, operation_id='list_members')
def list_members(organization_id: str, request: Request):
    service, session = workflow(request)
    return MemberList(items=service.members(session, organization_id))


@router.patch('/api/v1/workspaces/{organization_id}/members/{user_id}', status_code=204, operation_id='change_member')
def change_member(organization_id: str, user_id: str, body: MemberChange, request: Request):
    service, session = workflow(request)
    service.change_member(session, organization_id, user_id, body.role, body.active, body.authorization_version)
    return Response(status_code=204)


@router.get('/api/v1/workspaces/{organization_id}/invitations', response_model=InvitationList, operation_id='list_invitations')
def list_invitations(organization_id: str, request: Request):
    service, session = workflow(request)
    return InvitationList(items=service.invitations(session, organization_id))


@router.post('/api/v1/workspaces/{organization_id}/members/{user_id}/ownership', status_code=204, operation_id='grant_ownership')
def grant_ownership(organization_id: str, user_id: str, body: OwnershipGrant, request: Request):
    service, session = workflow(request)
    service.grant_ownership(session, organization_id, user_id, body.authorization_version)
    return Response(status_code=204)


@router.post('/api/v1/workspaces/{organization_id}/invitations', response_model=InviteIssued, operation_id='create_invitation')
def create_invitation(organization_id: str, body: InviteRequest, request: Request):
    service, session = workflow(request)
    result = service.invite(session, organization_id, body.email, body.role)
    return InviteIssued(id=result.id, credential=result.credential)


@router.delete('/api/v1/workspaces/{organization_id}/invitations/{invitation_id}', status_code=204, operation_id='revoke_invitation')
def revoke_invitation(organization_id: str, invitation_id: str, request: Request):
    service, session = workflow(request)
    service.revoke_invitation(session, organization_id, invitation_id)
    return Response(status_code=204)


@router.post('/api/v1/invitations/respond', response_model=InvitationOutcome, operation_id='respond_invitation',
             responses={410: {'model': ErrorEnvelope, 'description': 'Invitation expired'}})
def respond_invitation(body: InvitationResponse, request: Request):
    service, session = workflow(request)
    return service.respond(session, body.credential.get_secret_value(), body.accept)
