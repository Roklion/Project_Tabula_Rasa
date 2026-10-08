"""Thin request composition; bookkeeping and transactions retain their owners."""

from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends

from ..context import RequestContext, resolve_context
from ..errors import TransportError

Context = Annotated[RequestContext, Depends(resolve_context)]


@contextmanager
def service_operation(request, context, name):
    runtime = request.app.state.runtime
    with runtime.operation():
        service = getattr(runtime.services(context), name)
        if service is None:
            raise TransportError('unavailable')
        yield service
