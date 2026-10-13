from fastapi import APIRouter, Request, Response

from ..context import require_csrf, resolve_context
from ..errors import ERROR_RESPONSES, TransportError
from ..models.common import EntityInfo, EntityList, EntitySelection, SessionInfo, SetupSessionInfo

router = APIRouter(responses=ERROR_RESPONSES)


@router.get("/api/v1/session", response_model=SessionInfo | SetupSessionInfo, tags=["Session"], operation_id="get_session")
def get_session(request: Request):
    runtime = request.app.state.runtime
    if getattr(runtime, "identity", None) is not None:
        return runtime.identity.info(runtime.identity.authenticated(request))
    return context_info(request, resolve_context(request))


def context_info(request, context):
    runtime = request.app.state.runtime
    with runtime.operation():
        info = runtime.services(context).ledger.get_info()
        return SessionInfo(
            actor_id=context.actor_id, organization_id=context.organization_id,
            entity=EntityInfo(id=context.entity_id, name=info.name),
            capabilities=sorted(context.capabilities), cache_scope=context.cache_scope,
            csrf_token=context.csrf_token, trusted_development=context.trusted_development,
        )


def available_contexts(request, context):
    resolver = request.app.state.runtime.resolve_context
    enumerate_contexts = getattr(resolver, 'available_contexts', None)
    return enumerate_contexts(request) if enumerate_contexts else (context,)


@router.get('/api/v1/entities', response_model=EntityList, tags=['Session'], operation_id='list_entities')
def list_entities(request: Request):
    runtime = request.app.state.runtime
    if getattr(runtime, "identity", None) is not None:
        session = runtime.identity.authenticated(request)
        return EntityList(items=[EntityInfo(id=item.entity_id, name=item.name)
                                for item in runtime.identity.sessions.identity.allowed_entities(session.user_id)])
    context = resolve_context(request)
    with runtime.operation():
        return EntityList(items=[EntityInfo(id=item.entity_id, name=runtime.services(item).ledger.get_info().name)
                                 for item in available_contexts(request, context)])


@router.post('/api/v1/session/entity', response_model=SessionInfo, tags=['Session'], operation_id='select_entity')
def select_entity(body: EntitySelection, request: Request, response: Response):
    runtime = request.app.state.runtime
    if getattr(runtime, "identity", None) is not None:
        auth = runtime.identity
        session = auth.authenticated(request)
        require_csrf(request, session.csrf_token)
        selected = auth.sessions.select(request.cookies.get(auth.session_cookie, ""), body.entity_id)
        return auth.info(selected)
    context = resolve_context(request)
    resolver = runtime.resolve_context
    # Selection is functional alpha context, never proof of membership. Only the
    # configured development resolver implements this cookie-based seam; #222
    # owns selection for authenticated sessions.
    from ..context import TrustedDevelopmentContext
    if not isinstance(resolver, TrustedDevelopmentContext):
        raise TransportError('forbidden')
    selected = next((item for item in available_contexts(request, context) if item.entity_id == body.entity_id), None)
    if selected is None:
        raise TransportError('forbidden')
    result = context_info(request, selected)
    response.set_cookie('tabula_entity', selected.entity_id, httponly=True, samesite='strict',
                        secure=request.app.state.settings.public_origin.startswith('https://'))
    return result
