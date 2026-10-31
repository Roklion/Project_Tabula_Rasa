"""Deployment opt-in must not borrow credentials or trust an unregistered origin."""
import json

import pytest

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.http.drive_oauth import CALLBACK_PATH, load_customer_oauth
from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG


def test_customer_oauth_configuration_is_explicit_and_exact(tmp_path):
    assert load_customer_oauth({}, 'https://app.example.test') is None
    path = tmp_path / 'synthetic-oauth.json'
    config = {**GOOGLE_OAUTH_CONFIG, 'redirect_uris': ['https://app.example.test' + CALLBACK_PATH]}
    path.write_text(json.dumps({'google_drive_oauth': config}), encoding='utf-8')
    env = {'TABULA_RASA_CUSTOMER_DRIVE_OAUTH_FILE': str(path)}
    assert load_customer_oauth(env, 'https://app.example.test').client_id == 'fake-client'
    with pytest.raises(IdentityError, match='unavailable') as error:
        load_customer_oauth(env, 'https://foreign.example.test')
    assert error.value.__context__ is None
    path.write_text('invalid-private-configuration', encoding='utf-8')
    with pytest.raises(IdentityError, match='unavailable') as error:
        load_customer_oauth(env, 'https://app.example.test')
    assert 'invalid-private' not in str(error.value)
    with pytest.raises(IdentityError):
        load_customer_oauth({'TABULA_RASA_CUSTOMER_DRIVE_OAUTH_FILE': 'relative.json'}, 'https://app.example.test')
