"""FastAPI factory, process lifecycle and safe request instrumentation."""

from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import re
from time import perf_counter
from uuid import uuid4

from anyio import CapacityLimiter, to_thread
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse
from .static import HashedAssets
from .alpha import PUBLIC_PROBES, gate_response

from tabula_rasa.errors import StorageError
from tabula_rasa.application.mileage import MileageValidationError
from .composition import open_runtime
from .config import HttpSettings
from .errors import (
    TransportError, error_response, handle_error, handle_http_error, handle_validation,
)
from .models.common import Health, Version
from .routes import accounting, accounts, mileage, references, session

logger = logging.getLogger("tabula_rasa.http")


def create_app(*, settings=None, runtime_factory=None, schema_only=False, static_dir=None):
    """#222 injects a server resolver/runtime factory; export skips all runtime access."""
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or HttpSettings.from_environment()
        app.state.alpha_workers = CapacityLimiter(2)
        factory = runtime_factory or open_runtime
        app.state.runtime = await run_in_threadpool(factory, app.state.settings)
        try:
            yield
        finally:
            await run_in_threadpool(app.state.runtime.close)

    logging.getLogger("uvicorn.access").disabled = True
    app = FastAPI(
        title="Tabula Rasa commercial API", version="1.0.0",
        lifespan=None if schema_only else lifespan,
        docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json",
    )
    app.add_exception_handler(TransportError, handle_error)
    app.add_exception_handler(StorageError, handle_error)
    app.add_exception_handler(MileageValidationError, handle_error)
    app.add_exception_handler(RequestValidationError, handle_validation)
    app.add_exception_handler(HTTPException, handle_http_error)

    @app.middleware("http")
    async def safe_request(request: Request, call_next):
        started = perf_counter()
        request.state.request_id = uuid4().hex
        correlation = request.headers.get("x-correlation-id", "")
        request.state.correlation_id = (
            correlation if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", correlation) else None
        )
        try:
            configured = getattr(app.state, "settings", None)
            if (configured and request.url.path not in {"/health/live", "/health/ready", "/version"}
                    and (request.headers.get("host") or "").lower() != configured.public_origin.split("://", 1)[1].lower()):
                response = error_response(request, "forbidden")
            else:
                if configured and configured.hosted_alpha and request.url.path not in PUBLIC_PROBES:
                    response = await to_thread.run_sync(
                        gate_response, request, configured, limiter=app.state.alpha_workers,
                    )
                else:
                    response = gate_response(request, configured) if configured else None
                if response is None and (request.url.path in {"/api/docs", "/api/openapi.json"}
                        or (configured and configured.hosted_alpha and request.method not in {"GET", "HEAD", "OPTIONS"})):
                    from .context import resolve_context
                    await run_in_threadpool(resolve_context, request)
                if response is None:
                    response = await call_next(request)
        except TransportError as error:
            response = error_response(request, error.code)
        except Exception:
            # Do not emit exception repr/tracebacks: they may contain SQL or draft values.
            response = error_response(request, "unexpected")
        response.headers["X-Request-ID"] = request.state.request_id
        if configured and configured.hosted_alpha:
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers.setdefault("Cache-Control", "no-store")
        route = request.scope.get("route")
        logger.info(json.dumps({
            "request_id": request.state.request_id,
            "correlation_id": request.state.correlation_id,
            "method": request.method if request.method in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} else "OTHER",
            "route": getattr(route, "path", "unmatched"),
            "status": response.status_code,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
            "release": configured.release_id if configured else "schema",
            "failure_code": getattr(request.state, "failure_code", None),
        }, sort_keys=True))
        return response

    @app.get("/health/live", response_model=Health, tags=["Runtime"], operation_id="liveness")
    def live():
        return Health(status="live")

    @app.get("/health/ready", response_model=Health, responses={503: {"model": Health}},
             tags=["Runtime"], operation_id="readiness")
    def ready(request: Request):
        from starlette.responses import JSONResponse
        try:
            healthy = request.app.state.runtime.ready()
        except Exception:
            healthy = False
        return JSONResponse({"status": "ready" if healthy else "unavailable"}, status_code=200 if healthy else 503)

    @app.get("/version", response_model=Version, tags=["Runtime"], operation_id="version")
    def version(request: Request):
        return Version(release=request.app.state.settings.release_id)

    app.include_router(session.router)
    app.include_router(accounts.router)
    app.include_router(references.categories)
    app.include_router(references.payees)
    app.include_router(references.tags)
    app.include_router(accounting.transactions)
    app.include_router(accounting.journals)
    app.include_router(mileage.router)
    assets = Path(static_dir) if static_dir is not None else Path(__file__).resolve().parents[2] / "web" / "dist"
    if not schema_only and assets.is_dir():
        app.mount("/assets", HashedAssets(directory=assets / "assets"), name="assets")

        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        def browser(request: Request, path: str):
            if (path.split("/", 1)[0] in {"api", "health", "version", "assets"}
                    or "." in path or "text/html" not in request.headers.get("accept", "")):
                raise HTTPException(404)
            return FileResponse(assets / "index.html", headers={"Cache-Control": "no-cache"})

    return app
