"""Validate the local Sheets dashboard with protected split configuration."""

from __future__ import annotations

import secrets
import sys
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from streamlit.testing.v1 import AppTest

from tabula_rasa.ledger_auth import hash_password


def _validate_dashboard(
    app_secrets: dict,
    test_password: str,
) -> None:
    st.cache_resource.clear()
    app = AppTest.from_file(
        PROJECT_ROOT / "tabula_rasa" / "app.py",
        default_timeout=60,
    )
    app.secrets.update(app_secrets)
    app.run()
    app.text_input[0].input(test_password)
    app.button[0].click().run()

    if app.exception:
        raise RuntimeError(
            "The local Google-backed dashboard raised an exception"
        )
    if not app.radio or app.radio[0].label != "Navigate":
        raise RuntimeError(
            "The local authenticated navigation did not render"
        )
    if len(app.metric) != 4:
        raise RuntimeError(
            "The local dashboard summary metrics did not render"
        )
    print("Live dashboard validation passed: split local secrets")


def main() -> None:
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    with secrets_path.open("rb") as secrets_file:
        local_app_secrets = tomllib.load(secrets_file)

    test_password = secrets.token_urlsafe(24)
    test_password_hash = hash_password(test_password)

    local_app_secrets["app_password_hash"] = test_password_hash
    _validate_dashboard(
        local_app_secrets,
        test_password,
    )


if __name__ == "__main__":
    main()
