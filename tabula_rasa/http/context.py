"""#222 replaces the resolver; path/body/header IDs never grant access."""

from dataclasses import dataclass, field
from hmac import compare_digest
from typing import Protocol

from fastapi import Request

from .errors import TransportError


@dataclass(frozen=True)
class RequestContext:
    actor_id: str
    organization_id: str
    entity_id: str
    capabilities: frozenset[str]
    cache_scope: str
    csrf_token: str = field(repr=False)
    trusted_development: bool = False


class ContextResolver(Protocol):
    def __call__(self, request: Request) -> RequestContext: ...


class DenyContext:
    def __call__(self, request):
        raise TransportError("unauthorized")


class TrustedDevelopmentContext:
    """Fixed synthetic scope, server configured; requires loopback on every request."""

    def __init__(self, entity_id, csrf_token):
        self.context = RequestContext(
            "synthetic-operator", "synthetic", entity_id,
            frozenset({"bookkeeping:read", "bookkeeping:write"}),
            "development:" + entity_id, csrf_token, True,
        )

    def __call__(self, request):
        if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
            raise TransportError("forbidden")
        return self.context


def resolve_context(request: Request) -> RequestContext:
    context = request.app.state.runtime.resolve_context(request)
    if not isinstance(context, RequestContext):
        raise TransportError("unauthorized")
    requested = request.path_params.get("entity_id")
    if requested is not None and requested != context.entity_id:
        raise TransportError("forbidden")
    unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
    capability = "bookkeeping:write" if unsafe else "bookkeeping:read"
    if capability not in context.capabilities:
        raise TransportError("forbidden")
    if unsafe:
        origin = request.headers.get("origin", "")
        csrf = request.headers.get("x-csrf-token", "")
        if (origin != request.app.state.settings.public_origin
                or not csrf or not context.csrf_token
                or not compare_digest(csrf.encode(), context.csrf_token.encode())):
            raise TransportError("forbidden")
    return context
