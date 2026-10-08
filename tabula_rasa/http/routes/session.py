from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ..context import RequestContext, resolve_context
from ..errors import ERROR_RESPONSES
from ..models.common import EntityInfo, SessionInfo

router = APIRouter(responses=ERROR_RESPONSES)


@router.get("/api/v1/session", response_model=SessionInfo, tags=["Session"], operation_id="get_session")
def get_session(request: Request, context: Annotated[RequestContext, Depends(resolve_context)]):
    runtime = request.app.state.runtime
    with runtime.operation():
        info = runtime.services(context).ledger.get_info()
        return SessionInfo(
            actor_id=context.actor_id, organization_id=context.organization_id,
            entity=EntityInfo(id=context.entity_id, name=info.name),
            capabilities=sorted(context.capabilities), cache_scope=context.cache_scope,
            csrf_token=context.csrf_token, trusted_development=context.trusted_development,
        )
