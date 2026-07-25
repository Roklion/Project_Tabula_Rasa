"""Validate local and hosted secrets modes against the live dashboard."""

from __future__ import annotations

import secrets
import sys
import tempfile
import tomllib
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from streamlit.testing.v1 import AppTest

from ledger_auth import hash_password
from local_profile_store import LOCAL_PROFILE_STORE_PATH, load_local_profiles
from scripts.export_streamlit_secrets import build_streamlit_secrets_toml


def _validate_dashboard(
    app_secrets: dict,
    test_password: str,
    *,
    mode: str,
    local_profile_path: Path | None = None,
) -> None:
    st.cache_resource.clear()
    if local_profile_path is None:
        app = AppTest.from_file(PROJECT_ROOT / "app.py", default_timeout=60)
        app.secrets.update(app_secrets)
        app.run()
        app.text_input[0].input(test_password)
        app.button[0].click().run()
    else:
        with patch(
            "local_profile_store.LOCAL_PROFILE_STORE_PATH",
            local_profile_path,
        ):
            app = AppTest.from_file(PROJECT_ROOT / "app.py", default_timeout=60)
            app.secrets.update(app_secrets)
            app.run()
            app.text_input[0].input(test_password)
            app.button[0].click().run()

    if app.exception:
        raise RuntimeError(
            f"The {mode} Google-backed dashboard raised an exception"
        )
    if not app.radio or app.radio[0].label != "Navigate":
        raise RuntimeError(
            f"The {mode} authenticated navigation did not render"
        )
    if len(app.metric) != 4:
        raise RuntimeError(
            f"The {mode} dashboard summary metrics did not render"
        )
    print(f"Live dashboard validation passed: {mode}")


def main() -> None:
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    with secrets_path.open("rb") as secrets_file:
        local_app_secrets = tomllib.load(secrets_file)
    profiles = load_local_profiles(LOCAL_PROFILE_STORE_PATH)

    test_password = secrets.token_urlsafe(24)
    test_password_hash = hash_password(test_password)

    local_app_secrets["app_password_hash"] = test_password_hash
    _validate_dashboard(
        local_app_secrets,
        test_password,
        mode="split local secrets",
    )

    hosted_document = build_streamlit_secrets_toml(
        local_app_secrets,
        profiles,
    )
    hosted_secrets = tomllib.loads(hosted_document)
    hosted_secrets["app_password_hash"] = test_password_hash
    with tempfile.TemporaryDirectory() as directory:
        absent_local_profile_path = Path(directory) / "business_profiles.json"
        _validate_dashboard(
            hosted_secrets,
            test_password,
            mode="hosted Streamlit Secrets",
            local_profile_path=absent_local_profile_path,
        )


if __name__ == "__main__":
    main()
