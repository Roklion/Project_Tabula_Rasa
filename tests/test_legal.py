"""Public legal-route and content boundary tests."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.legal import legal_document_path


def _markdown_text(app: AppTest) -> str:
    return "\n".join(str(item.value) for item in app.markdown)


def test_legal_document_routes_are_strictly_allowlisted() -> None:
    assert legal_document_path("terms").name == "TERMS_OF_USE.md"  # type: ignore[union-attr]
    assert legal_document_path("privacy").name == "PRIVACY_POLICY.md"  # type: ignore[union-attr]
    assert legal_document_path("../.streamlit/secrets.toml") is None
    assert legal_document_path(None) is None


def test_public_terms_render_before_authentication_or_profile_loading() -> None:
    app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
    app.query_params["legal"] = "terms"

    app.run()

    text = _markdown_text(app)
    assert len(app.exception) == 0
    assert "# Terms of Use" in text
    assert "Google Maps/Google Earth Additional Terms of Service" in text
    assert "Terms of Use" in text and "Privacy Policy" in text
    assert len(app.text_input) == 0
    assert len(app.radio) == 0
    assert "Workbook:" not in text


def test_login_surface_exposes_global_legal_footer() -> None:
    app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
    app.secrets["app_password_hash"] = hash_password("test-password-123")

    app.run()

    text = _markdown_text(app)
    assert len(app.exception) == 0
    assert app.text_input[0].label == "Password"
    assert "[Terms of Use](?legal=terms)" in text
    assert "[Privacy Policy](?legal=privacy)" in text


def test_authenticated_surface_exposes_global_legal_footer() -> None:
    app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
    app.secrets["app_password_hash"] = hash_password("test-password-123")

    app.run()
    app.text_input[0].input("test-password-123")
    app.button[0].click().run()

    text = _markdown_text(app)
    assert len(app.exception) == 0
    assert "[Terms of Use](?legal=terms)" in text
    assert "[Privacy Policy](?legal=privacy)" in text


def test_checked_in_legal_content_includes_google_policy_links() -> None:
    terms = legal_document_path("terms").read_text(encoding="utf-8")  # type: ignore[union-attr]
    privacy = legal_document_path("privacy").read_text(encoding="utf-8")  # type: ignore[union-attr]

    for content, heading in (
        (terms, "# Terms of Use"),
        (privacy, "# Privacy Policy"),
    ):
        assert heading in content
        assert "**Effective Date:** August 31, 2026" in content
        assert "https://maps.google.com/help/terms_maps/" in content
        assert "https://policies.google.com/privacy" in content
