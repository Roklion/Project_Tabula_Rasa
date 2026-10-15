"""Explicit registered HTTP actions; future private routes deny by default."""

from dataclasses import dataclass
from types import MappingProxyType

from fastapi import Request
from fastapi.routing import APIRoute, iter_route_contexts

from tabula_rasa.application.authorization import ACTION_CAPABILITIES

from .errors import TransportError


@dataclass(frozen=True)
class RoutePolicy:
    method: str
    action: str
    scope: str = 'entity'


# IDs are server route metadata, never request claims. Identity handlers share
# the session guard; logout retains its documented outage-clearing path.
ROUTE_POLICIES = MappingProxyType({
    **{name: RoutePolicy('GET', 'read') for name in (
        'list_accounts', 'list_categories', 'list_payees', 'list_tags',
        'list_transactions', 'list_journals', 'list_mileage', 'get_mileage',
        'unreferenced_documents', 'download_document', 'transaction_documents',
        'query_ledger', 'report_summary', 'list_mixed_use', 'get_mixed_use',
        'list_recurring', 'get_recurring', 'asset_types', 'list_assets', 'get_asset',
        'download_transactions_csv', 'download_journal_postings_csv',
        'download_selected_ledger_csv', 'mixed_use_documents', 'mileage_maps',
    )},
    **{name: RoutePolicy('POST', 'write') for name in (
        'create_account', 'deactivate_account', 'create_category', 'create_payee',
        'create_tag', 'merge_payees', 'merge_tags', 'create_transaction', 'create_journal',
        'create_mileage', 'link_document', 'create_mixed_use', 'create_recurring',
        'reconcile_recurring', 'transition_recurring', 'create_asset', 'post_depreciation',
        'link_mixed_use_document', 'calculate_mileage_route',
        'bulk_update_transactions', 'bulk_delete_transactions', 'convert_expense_to_recurring',
    )},
    **{name: RoutePolicy('PATCH', 'write') for name in (
        'update_account', 'update_category', 'update_payee', 'update_tag',
        'update_transaction', 'update_journal', 'update_mileage', 'update_mixed_use',
        'update_recurring', 'update_asset',
    )},
    **{name: RoutePolicy('DELETE', 'write') for name in (
        'delete_category', 'remove_payee', 'remove_tag', 'delete_transaction',
        'delete_journal', 'delete_mileage', 'unlink_document', 'delete_mixed_use',
        'delete_asset', 'remove_depreciation_override',
        'unlink_mixed_use_document',
    )},
    'upload_document': RoutePolicy('PUT', 'write'),
    'override_depreciation': RoutePolicy('PUT', 'write'),
    'prepare_selected_ledger_csv': RoutePolicy('POST', 'read'),
    'preview_allocation': RoutePolicy('POST', 'read'),
    'prepare_transaction_copy': RoutePolicy('POST', 'read'),
    'copy_mixed_use_draft': RoutePolicy('POST', 'read'),
    **{name: RoutePolicy('POST', 'import') for name in (
        'prepare_transaction_csv', 'preview_quickbooks_transactions', 'preview_quickbooks_mileage',
        'import_transaction_csv', 'import_quickbooks_transactions', 'import_quickbooks_mileage',
    )},
    'get_session': RoutePolicy('GET', 'read', 'identity'),
    'list_entities': RoutePolicy('GET', 'read', 'identity'),
    'select_entity': RoutePolicy('POST', 'read', 'identity'),
    'session_activity': RoutePolicy('POST', 'session', 'identity'),
    'revoke_all_sessions': RoutePolicy('POST', 'session', 'identity'),
    'logout': RoutePolicy('POST', 'logout', 'identity'),
    'logout_context': RoutePolicy('GET', 'logout', 'identity'),
    'begin_login': RoutePolicy('GET', 'login', 'public'),
    'complete_login': RoutePolicy('GET', 'callback', 'public'),
})


def route_policy(request):
    route = request.scope.get('route')
    policy = ROUTE_POLICIES.get(getattr(route, 'operation_id', None))
    entity_route = 'entity_id' in request.path_params
    if (policy is None or request.method != policy.method
            or (policy.scope == 'entity') != entity_route):
        request.state.security_event = 'authorization_denied'
        raise TransportError('forbidden')
    return policy


def authorize_request(request: Request):
    """App-wide dependency executes before every private handler's binding."""
    if not request.url.path.startswith('/api/'):
        return
    if getattr(request.scope.get('route'), 'path', None) == '/{path:path}':
        # The public SPA catch-all must never serve or bind a reserved API URL.
        raise TransportError('not_found')
    from .context import require_named_resolver
    require_named_resolver(request)
    policy = route_policy(request)
    if policy.scope == 'entity':
        from .context import resolve_context
        resolve_context(request)
    elif policy.scope == 'identity' and policy.action != 'logout':
        from .context import require_csrf, resolve_context
        identity = getattr(request.app.state.runtime, 'identity', None)
        if identity is None:
            resolve_context(request)  # Existing restricted-alpha session/selector.
        else:
            session = identity.authenticated(request)
            if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                require_csrf(request, session.csrf_token)


def validate_routes(app):
    """Catch missing actions, guards, duplicate IDs and mismatched scopes at build."""
    seen = set()
    for route in iter_route_contexts(app.routes):
        if not route.path or not (route.path == '/api' or route.path.startswith('/api/')):
            continue
        if route.path in {'/api/docs', '/api/openapi.json'} and not isinstance(route.original_route, APIRoute):
            continue  # Existing middleware protects framework documentation.
        if not isinstance(route.original_route, APIRoute):
            raise RuntimeError('Private API routes must use the shared FastAPI authorization guard.')
        policy = ROUTE_POLICIES.get(route.operation_id)
        allowed_actions = {'entity': ACTION_CAPABILITIES, 'identity': {'read', 'session', 'logout'},
                           'public': {'login', 'callback'}}
        if (policy is None or policy.action not in allowed_actions.get(policy.scope, ())
                or route.operation_id in seen or route.methods != {policy.method}
                or (policy.scope == 'entity') != ('{entity_id}' in route.path)
                or not any(item.call is authorize_request for item in route.dependant.dependencies)):
            raise RuntimeError('Private API route requires an explicit action and authorization guard.')
        seen.add(route.operation_id)
