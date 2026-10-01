"""Public, synthetic Google OAuth settings for tests; never deployment credentials."""

GOOGLE_OAUTH_CONFIG = {
    "client_id": "fake-client",
    "client_secret": "fake-secret",
    "redirect_uris": ["http://localhost:8501/"],
}


def google_grant(email="owner@example.test", token="fake-refresh"):
    return {
        "authorized_email": email,
        "authorized_name": "Owner",
        "refresh_token": token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/drive.file"],
    }
