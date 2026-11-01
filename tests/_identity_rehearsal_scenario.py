"""Loopback-only real TLS/Requests/OIDC resolver-failure feasibility, not hosted evidence."""

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import time
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from tabula_rasa.infrastructure.oidc import OidcProvider, OidcSettings
from tabula_rasa.application.identity import IdentityError
from tabula_rasa.http.identity_rehearsal import ResolverGate

ROOT = Path(tempfile.gettempdir())
server = None
clients = []
phase = "source_identity"
directory = tempfile.TemporaryDirectory(prefix="oidc-loopback-feasibility-", dir=ROOT)
fixture = Path(directory.name).resolve()
if not fixture.is_relative_to(ROOT.resolve()):
    raise ValueError("Unsafe local cleanup target")
try:
    phase = "synthetic_TLS_fixture"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic loopback feasibility")]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = fixture / "local-only-ca.pem"
    key_path = fixture / "local-only-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            hits.append(self.path)
            origin = "https://" + self.headers["Host"]
            value = {
                "issuer": origin,
                "authorization_endpoint": origin + "/authorize",
                "token_endpoint": origin + "/token",
                "jwks_uri": origin + "/keys",
                "userinfo_endpoint": origin + "/userinfo",
                "id_token_signing_alg_values_supported": ["RS256"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["client_secret_basic"],
            }
            body = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.05), daemon=True
    )
    thread.start()
    port = server.server_address[1]

    def provider(host):
        settings = OidcSettings(
            "https://" + host + ":" + str(port),
            "synthetic-client",
            "synthetic-only-secret",
            "s" * 64,
            "test",
            "https://synthetic.invalid",
        )
        instance = OidcProvider(settings)
        instance.transport.verify = str(cert_path)
        assert instance.transport.trust_env is False
        clients.append(instance)
        return instance

    phase = "baseline_transport"
    baseline = provider("localhost")
    with baseline.transport.get(
        baseline.settings.issuer + "/.well-known/openid-configuration",
        timeout=(1, 1),
        allow_redirects=False,
    ) as response:
        assert response.status_code == 200
    phase = "baseline_OIDC_metadata"
    assert baseline.metadata()["issuer"] == baseline.settings.issuer
    cold = provider("localhost")
    fault_end = time.monotonic() + 3.0
    gate = ResolverGate(
        cold.settings.issuer, datetime.now(timezone.utc) + timedelta(seconds=3), 3
    )
    sys.addaudithook(gate)
    before = len(hits)
    assert baseline.metadata()["issuer"] == baseline.settings.issuer
    assert len(hits) == before
    phase = "resolver_fault"
    before = len(hits)
    try:
        cold.metadata()
    except IdentityError as error:
        assert error.code == "unavailable"
    else:
        raise AssertionError("Cold metadata unexpectedly succeeded")
    assert len(hits) == before and cold._metadata is None
    if '--transport-only' not in sys.argv:
        phase = "HTTP_fail_closed"
        import io
        import logging
        from unittest.mock import Mock
        from fastapi.testclient import TestClient
        from tabula_rasa.application.identity import LoginTransaction
        from tabula_rasa.http.app import create_app
        from tabula_rasa.http.config import HttpSettings
        from tabula_rasa.http.identity import NamedIdentity

        settings = HttpSettings("test", "http://127.0.0.1", access_mode="named_user")
        sessions = Mock()
        sessions.begin_login.return_value = (
            "synthetic-login",
            LoginTransaction("s" * 43, "n" * 43, "v" * 64, "/"),
        )
        auth = NamedIdentity(settings, sessions, cold)
        runtime = Mock()
        runtime.identity = auth
        runtime.resolve_context = auth
        output = io.StringIO()
        logger = logging.getLogger("tabula_rasa.http")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(output)
        logger.addHandler(handler)
        with TestClient(
            create_app(settings=settings, runtime_factory=lambda _: runtime),
            base_url=settings.public_origin,
        ) as client:
            response = client.get("/api/v1/auth/login", follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"].startswith(
                "/signed-out?reason=unavailable&category=login_start&reference="
            )
            assert auth.session_cookie not in client.cookies
            assert auth.login_cookie not in client.cookies
            assert response.headers["referrer-policy"] == "no-referrer"
            assert response.headers["cache-control"] == "no-store"
            sessions.issue.assert_not_called()
            runtime.services.assert_not_called()
        logger.removeHandler(handler)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        event = next((item for item in events if item.get("operation") == "begin_login"))
        assert (
            event["security_event"] == "login_failed"
            and event["failure_code"] == "unavailable"
        )
        assert (
            event["security_reason"] == "login_start"
            and event["provider_status"] == "unavailable"
        )
        assert all(
            (
                value not in output.getvalue()
                for value in ("localhost", "synthetic-only-secret", "synthetic-login")
            )
        )
    phase = "unaffected_hostname_control"
    control = provider("127.0.0.1")
    assert control.metadata()["issuer"] == control.settings.issuer
    remaining = fault_end - time.monotonic()
    if remaining > 0:
        time.sleep(remaining + 0.01)
    phase = "automatic_restoration"
    assert cold.metadata()["issuer"] == cold.settings.issuer
    print(
        "synthetic TLS cold failure, same-server control, warm cache and restoration passed"
    )
except Exception as error:
    chain = []
    seen = set()
    item = error
    while item is not None and id(item) not in seen:
        seen.add(id(item))
        chain.append(type(item).__name__)
        item = item.__cause__ or item.__context__
    print(
        json.dumps(
            {
                "status": "loopback_feasibility_stopped",
                "phase": phase,
                "error_types": chain,
                "hosted_execution": False,
                "external_requests": 0,
            }
        )
    )
    raise SystemExit(1) from None
finally:
    for client in clients:
        client.close()
    if server is not None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert fixture.is_relative_to(ROOT.resolve())
    directory.cleanup()
