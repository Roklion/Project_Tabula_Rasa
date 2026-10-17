from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse, Response

from tabula_rasa.application.identity import IdentityError
from ..context import require_csrf
from ..errors import ERROR_RESPONSES, TransportError, error_response
from ..models.common import LogoutContext

router = APIRouter(responses=ERROR_RESPONSES, tags=["Authentication"])


def identity(request):
    result = getattr(request.app.state.runtime, "identity", None)
    if result is None:
        raise TransportError("forbidden")
    return result


@router.get("/api/v1/auth/login", operation_id="begin_login")
def login(request: Request, return_path: str = "/"):
    auth = identity(request)
    raw, transaction = auth.sessions.begin_login(return_path, request.cookies.get(auth.login_cookie))
    response = RedirectResponse(auth.provider.authorization_url(transaction), status_code=303)
    response.headers['Referrer-Policy'] = 'no-referrer'
    auth.set_cookie(response, auth.login_cookie, raw, 300)
    request.state.security_event = "login_started"
    return response


@router.get("/api/v1/auth/callback", operation_id="complete_login")
def callback(request: Request):
    auth = identity(request)
    # Consume even provider-denied/invalid callbacks. Exchange failures cannot be replayed.
    try:
        transaction = auth.sessions.consume_login(request.cookies.get(auth.login_cookie, ""),
                                                 request.query_params.get("state", ""))
        if "error" in request.query_params:
            raise IdentityError("unauthorized")
        verified = auth.provider.verify(request.query_params.get("code", ""), transaction)
        raw, session = auth.sessions.issue(verified, request.cookies.get(auth.session_cookie))
        response = RedirectResponse(transaction.return_path, status_code=303)
        auth.set_cookie(response, auth.session_cookie, raw, 43200)
        auth.set_cookie(response, auth.csrf_cookie, session.csrf_token, 43200)
        request.state.named_session = session
        request.state.security_event = "login_succeeded"
    except IdentityError as error:
        response = RedirectResponse("/signed-out?reason=" + ("unavailable" if error.code == "unavailable" else "login_failed"), status_code=303)
        request.state.failure_code = error.code
        request.state.security_event = "login_failed"
    auth.clear(response, login_only=True)
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@router.get("/api/v1/auth/logout-context", response_model=LogoutContext, operation_id="logout_context")
def logout_context(request: Request):
    auth = identity(request)
    # A same-origin read of the logout-only cookie, not an authenticated session.
    # The custom header requires preflight cross-origin; this API grants no CORS.
    if (request.headers.get("x-tabula-logout") != "1"
            or request.headers.get("sec-fetch-site", "same-origin") != "same-origin"
            or request.headers.get("origin", auth.settings.public_origin) != auth.settings.public_origin):
        raise TransportError("forbidden")
    token = request.cookies.get(auth.csrf_cookie, "")
    if not token:
        raise TransportError("unauthorized")
    return LogoutContext(csrf_token=token)


@router.post("/api/v1/auth/logout", status_code=204, operation_id="logout")
def logout(request: Request):
    auth = identity(request)
    # Host-only HttpOnly synchronizer copy permits local clearing during DB outage;
    # it grants no entity authority and does not claim server revocation succeeded.
    require_csrf(request, request.cookies.get(auth.csrf_cookie, ""))
    try:
        auth.sessions.revoke(request.cookies.get(auth.session_cookie, ""))
        response = Response(status_code=204)
        request.state.security_event = "logout_succeeded"
    except IdentityError as error:
        response = Response(status_code=204) if error.code == "unauthorized" else error_response(request, error.code)
        request.state.security_event = "logout_local" if error.code == "unauthorized" else "logout_failed"
    auth.clear(response)
    return response


@router.post("/api/v1/auth/activity", status_code=204, operation_id="session_activity")
def activity(request: Request):
    auth = identity(request)
    session = auth.authenticated(request)
    require_csrf(request, session.csrf_token)
    auth.authenticated(request, foreground=True)
    return Response(status_code=204)


@router.post("/api/v1/auth/revoke-all", status_code=204, operation_id="revoke_all_sessions")
def revoke_all(request: Request):
    auth = identity(request)
    session = auth.authenticated(request)
    require_csrf(request, session.csrf_token)
    auth.sessions.identity.revoke_user_sessions(session.user_id)
    response = Response(status_code=204)
    auth.clear(response)
    request.state.security_event = "user_sessions_revoked"
    return response
