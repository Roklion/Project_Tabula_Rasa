"""Run a live read-only Streamlit dashboard check with isolated test authentication."""

from __future__ import annotations

import secrets
import sys
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest

from ledger_auth import hash_password


def main() -> None:
    with (PROJECT_ROOT / ".streamlit" / "secrets.toml").open("rb") as secrets_file:
        app_secrets = tomllib.load(secrets_file)

    test_password = secrets.token_urlsafe(24)
    app_secrets["app_password_hash"] = hash_password(test_password)
    app = AppTest.from_file(PROJECT_ROOT / "app.py", default_timeout=60)
    app.secrets.update(app_secrets)
    app.run()
    app.text_input[0].input(test_password)
    app.button[0].click().run()

    if app.exception:
        raise RuntimeError("The Google-backed Streamlit dashboard raised an exception")
    if not app.radio or app.radio[0].label != "Navigate":
        raise RuntimeError("The authenticated navigation did not render")
    if len(app.metric) != 4:
        raise RuntimeError("The dashboard summary metrics did not render")

    print("Live Google-backed Streamlit dashboard validation passed")


if __name__ == "__main__":
    main()
