"""Read-only restricted-alpha telemetry exercise; never inject an API crash route."""

import argparse
import json
import os
import re

import requests

from tabula_rasa.http.config import HttpSettings


def exercise(origin, username, password, release, *, session=None):
    """Only return release and server request IDs, never response bodies/claims."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", release):
        raise ValueError("Invalid smoke release.")
    owned = session is None
    session = session or requests.Session()
    session.trust_env = False
    trail = []
    try:
        def get(path, expected):
            response = session.get(origin + path, auth=(username, password),
                                   timeout=(5, 90), allow_redirects=False)
            if response.status_code != expected:
                raise ValueError("Observability smoke status mismatch.")
            request_id = response.headers.get("X-Request-ID", "")
            if not re.fullmatch(r"[a-f0-9]{32}", request_id):
                raise ValueError("Observability smoke correlation missing.")
            trail.append({"status": expected, "request_id": request_id})
            return response
        if get("/version", 200).json() != {"release": release}:
            raise ValueError("Observability smoke release mismatch.")
        # A controlled denial uses a fixed synthetic selector and never reads a
        # foreign tenant or changes the database. Recovery uses the allowed scope.
        get("/api/v1/entities/observability-smoke-denied/accounts", 403)
        get("/api/v1/entities/alpha-synthetic/accounts", 200)
        get("/health/ready", 200)
        return {"release": release, "requests": trail}
    finally:
        if owned:
            session.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    args = parser.parse_args()
    try:
        settings = HttpSettings.from_environment()
        if settings.environment != "staging" or not settings.hosted_alpha:
            raise ValueError("Restricted synthetic staging required.")
        result = exercise(settings.public_origin, settings.alpha_username,
            os.environ["TABULA_RASA_ALPHA_PASSWORD"], args.release)
    except Exception:
        raise SystemExit("Observability smoke failed; inspect safe request signals, staging binding and release.") from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
