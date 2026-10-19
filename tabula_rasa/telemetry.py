"""Bounded diagnostic telemetry. Never accept exception text or business payloads.

HTTP owns request/context extraction; this module owns redaction and delivery.
Logs are best effort diagnostics, not the immutable accounting history (#335).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import math
import os
from queue import Empty, Full, Queue
import re
from threading import Event, Thread
from time import monotonic

import requests

from tabula_rasa.application.identity import LOGIN_FAILURE_REASONS

logger = logging.getLogger("tabula_rasa.http")
SECURITY_EVENTS = frozenset({
    "login_started", "login_succeeded", "login_failed", "logout_succeeded",
    "logout_local", "logout_failed", "user_sessions_revoked", "identity_denied",
    "authorization_denied", "privileged_denied",
})
REASONS = frozenset({"cross_entity", "capability", "csrf", "policy", "identity"}) | LOGIN_FAILURE_REASONS
SIGNALS = frozenset({"http_request", "runtime", "job_run", "backup_run", "deployment"})
SYSTEM_OPERATIONS = frozenset({"startup", "shutdown", "job_execute", "backup_execute", "deploy"})
PROVIDERS = frozenset({"application", "postgresql", "identity", "documents", "telemetry"})
PROVIDER_STATUSES = frozenset({"ok", "unavailable", "exhausted", "not_configured"})


@dataclass(frozen=True)
class TelemetrySettings:
    endpoint: str = field(default="", repr=False)
    token: str = field(default="", repr=False)
    scope_key: str = field(default="", repr=False)

    def __post_init__(self):
        # Only a source-specific Better Stack HTTPS ingest host. No redirects,
        # URL credentials, paths, proxy environment or arbitrary HTTP destination.
        valid_endpoint = re.fullmatch(r"https://[a-z0-9-]+(?:\.[a-z0-9-]+)*\.betterstackdata\.com", self.endpoint)
        if (bool(self.endpoint) != bool(self.token)
                or self.endpoint and not valid_endpoint
                or self.token and not re.fullmatch(r"[A-Za-z0-9._-]{16,512}", self.token)
                or self.scope_key and len(self.scope_key) < 32):
            raise ValueError("Invalid telemetry configuration; check source binding and secret lengths.")

    @classmethod
    def from_environment(cls):
        return cls(*(os.environ.get("TABULA_RASA_TELEMETRY_" + name, "")
                     for name in ("ENDPOINT", "TOKEN", "SCOPE_KEY")))


def configure_console():
    """Called by the server entrypoint only; do not reconfigure test/host logging."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


class Telemetry:
    def __init__(self, environment, release, settings=None, *, routes=(), operations=(), actions=(), failure_codes=()):
        self.environment = environment if environment in {"development", "test", "staging", "production"} else "test"
        self.release = release if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", release) else "unknown"
        self.settings = settings or TelemetrySettings()
        self.routes = frozenset(routes)
        self.operations = frozenset(operations) | SYSTEM_OPERATIONS | {"unmatched", "static_assets"}
        self.actions = frozenset(actions)
        self.failure_codes = frozenset(failure_codes) | {"unavailable", "unexpected"}
        self.queue = Queue(maxsize=128)
        self.stopped = Event()
        self.last_delivery_notice = float("-inf")
        self.thread = None
        if self.settings.endpoint:
            self.thread = Thread(target=self._export, name="safe-telemetry", daemon=True)
            self.thread.start()

    def reference(self, kind, value):
        # Stable only inside this environment/key. No key means no scope export.
        if not self.settings.scope_key or not isinstance(value, str) or not value or len(value) > 1024:
            return None
        message = json.dumps([self.environment, kind, value], separators=(",", ":")).encode()
        return hmac.new(self.settings.scope_key.encode(), message, hashlib.sha256).hexdigest()[:24]

    def record(self, event, operation, *, request_id=None, correlation=None, route=None,
               method=None, status=None, duration_ms=None, failure_code=None,
               security_event=None, security_reason=None, action=None, context=None,
               actor_id=None, job_id=None, provider=None, provider_status=None, login_request_id=None):
        """Allowlist every field before either sink. Callers never supply a dict.

        operation/route/action come from the compiled HTTP registry, not a URL.
        System producers have a closed operation vocabulary pending #333/#294.
        """
        if event not in SIGNALS:
            return
        # Adapter registries are compiled server metadata. System/job producers
        # need no HTTP imports and use the closed system vocabulary by default.
        operation = operation if operation in self.operations else "unmatched"
        route = route if route in self.routes else "unmatched"
        code = failure_code if failure_code in self.failure_codes else "unexpected" if failure_code is not None else None
        security = security_event if security_event in SECURITY_EVENTS else None
        failed = (isinstance(status, int) and status >= 400) or code is not None or security in {
            "login_failed", "logout_failed", "identity_denied", "authorization_denied", "privileged_denied",
        } or provider_status in {"unavailable", "exhausted", "not_configured"}
        level = "error" if (isinstance(status, int) and status >= 500) or code in {"unexpected", "unavailable"} else "warning" if failed else "info"
        payload = {
            "schema_version": 1, "dt": datetime.now(timezone.utc).isoformat(),
            "event": event, "operation": operation, "stage": self.environment,
            "release": self.release, "level": level, "outcome": "failure" if failed else "success",
            "request_id": request_id if isinstance(request_id, str) and re.fullmatch(r"[a-f0-9]{32}", request_id) else None,
            "correlation_id": self.reference("correlation", correlation),
            "login_ref": self.reference("login", login_request_id) if isinstance(login_request_id, str) and re.fullmatch(r"[a-f0-9]{32}", login_request_id) else None,
            "route": route, "method": method if method in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} else "OTHER",
            "status": status if type(status) is int and 100 <= status <= 599 else None,
            "duration_ms": round(min(max(duration_ms, 0), 86400000), 2) if type(duration_ms) in {float, int} and math.isfinite(duration_ms) else None,
            "failure_code": code, "security_event": security,
            "security_reason": security_reason if security_reason in REASONS else None,
            "action": action if action in self.actions else None,
            "actor_ref": self.reference("actor", getattr(context, "actor_id", None) or actor_id),
            "organization_ref": self.reference("organization", getattr(context, "organization_id", None)),
            "entity_ref": self.reference("entity", getattr(context, "entity_id", None)),
            "job_ref": self.reference("job", job_id),
            "provider": provider if provider in PROVIDERS else "application",
            "provider_status": provider_status if provider_status in PROVIDER_STATUSES else None,
            "error_group": operation + ":" + (code or security or "http_failure") if failed else None,
        }
        encoded = json.dumps(payload, sort_keys=True)
        self._console(encoded, level)
        if self.thread and not self.stopped.is_set():
            try:
                self.queue.put_nowait(payload)
            except Full:
                self._delivery_notice("exhausted")
        return payload

    @staticmethod
    def _console(encoded, level):
        try:
            logger.log({"error": logging.ERROR, "warning": logging.WARNING, "info": logging.INFO}[level], encoded)
        except Exception:
            # A broken logging handler must not alter a committed business result.
            pass

    def _delivery_notice(self, status):
        now = monotonic()
        if now - self.last_delivery_notice < 60:
            return
        self.last_delivery_notice = now
        self._console(json.dumps({"schema_version": 1, "event": "telemetry_delivery",
            "dt": datetime.now(timezone.utc).isoformat(), "stage": self.environment,
            "release": self.release, "level": "error", "provider": "telemetry",
            "provider_status": status, "outcome": "failure"}, sort_keys=True), "error")

    def _export(self):
        try:
            session = requests.Session()
        except Exception:
            self._delivery_notice("unavailable")
            return
        with session:
            session.trust_env = False
            while not self.stopped.is_set():
                try:
                    batch = [self.queue.get(timeout=0.2)]
                except Empty:
                    continue
                while len(batch) < 32:
                    try:
                        batch.append(self.queue.get_nowait())
                    except Empty:
                        break
                try:
                    with session.post(self.settings.endpoint, json=batch,
                            headers={"Authorization": "Bearer " + self.settings.token},
                            timeout=(1, 2), allow_redirects=False, stream=True) as response:
                        if response.status_code != 202:
                            self._delivery_notice("exhausted" if response.status_code in {402, 429} else "unavailable")
                except Exception:
                    # Never log response bodies, destination, exception or token.
                    self._delivery_notice("unavailable")
                finally:
                    session.cookies.clear()

    def close(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=4)
            if self.thread.is_alive() or not self.queue.empty():
                self._delivery_notice("unavailable")
