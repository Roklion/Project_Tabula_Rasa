import json
from time import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from tabula_rasa.application.identity import IdentityError, LoginTransaction
from tabula_rasa.infrastructure.oidc import OidcProvider, OidcSettings


class ProviderResponse:
    status_code = 200
    def __init__(self, data):
        self.data = data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def iter_content(self, size):
        yield json.dumps(self.data).encode()


@pytest.fixture
def oidc():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = OidcSettings('https://id.example.test', 'client', 'secret', 'g' * 32, 'test', 'http://127.0.0.1')
    transaction = LoginTransaction('s' * 43, 'n' * 43, 'v' * 64, '/')
    claims = dict(iss=settings.issuer, sub='alice', aud='client', exp=int(time()) + 300,
                  iat=int(time()), nonce=transaction.nonce, auth_time=int(time()))
    info = dict(sub='alice', email='synthetic@example.test', email_verified=True)
    calls = []
    class Transport:
        token_override = None
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            if url.endswith('openid-configuration'):
                result = dict(issuer=settings.issuer, authorization_endpoint=settings.issuer + '/authorize',
                              token_endpoint=settings.issuer + '/token', jwks_uri=settings.issuer + '/keys',
                              userinfo_endpoint=settings.issuer + '/userinfo', id_token_signing_alg_values_supported=['RS256'],
                              code_challenge_methods_supported=['S256'], token_endpoint_auth_methods_supported=['client_secret_basic'])
            elif url.endswith('/token'):
                result = dict(id_token=self.token_override or jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'key'}),
                              access_token='synthetic-access', token_type='Bearer')
            elif url.endswith('/keys'):
                result = {'keys': [dict(json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())), kid='key')]}
            else:
                result = info
            return ProviderResponse(result)
        def close(self):
            pass
    return OidcProvider(settings, transport=Transport()), transaction, claims, info, calls


def test_code_pkce_verified_identity_and_bounded_transport(oidc):
    provider, transaction, _, _, calls = oidc
    query = parse_qs(urlsplit(provider.authorization_url(transaction)).query)
    assert query['code_challenge_method'] == ['S256'] and query['max_age'] == ['0']
    assert query['redirect_uri'] == [provider.settings.callback]
    result = provider.verify('synthetic-code', transaction)
    assert result.subject == 'alice'
    token_call = next(call for call in calls if call[0] == 'POST')
    assert token_call[2]['data']['code_verifier'] == transaction.verifier
    assert token_call[2]['auth'] == ('client', 'secret')
    assert all(call[2]['allow_redirects'] is False and call[2]['timeout'] == (3, 5) for call in calls)
    assert 'synthetic@example.test' not in repr(result)


@pytest.mark.parametrize('change', [dict(iss='https://wrong.test'), dict(aud='wrong'), dict(nonce='wrong'),
    dict(exp=lambda: int(time()) - 120), dict(iat=lambda: int(time()) + 120), dict(nbf=lambda: int(time()) + 120),
    dict(auth_time=lambda: int(time()) - 600), dict(auth_time=True), dict(azp='wrong'),
    dict(aud=['client', 'other']), dict(sub=''), dict(at_hash='wrong')])
def test_invalid_signed_claims_fail_closed_without_provider_material(oidc, change):
    provider, transaction, claims, _, _ = oidc
    # Resolve relative times at execution, not collection before a long suite.
    claims.update({key: value() if callable(value) else value for key, value in change.items()})
    with pytest.raises(IdentityError) as caught:
        provider.verify('synthetic-code', transaction)
    assert caught.value.code == 'unauthorized'
    assert caught.value.__context__ is None
    assert 'synthetic' not in str(caught.value)


@pytest.mark.parametrize('change', [dict(sub='bob'), dict(email_verified=False), dict(email_verified='true'), dict(email='')])
def test_userinfo_requires_same_subject_and_verified_email(oidc, change):
    provider, transaction, _, info, _ = oidc
    info.update(change)
    with pytest.raises(IdentityError):
        provider.verify('synthetic-code', transaction)


def test_unknown_key_refresh_and_untrusted_endpoint_rejected(oidc):
    provider, transaction, _, _, calls = oidc
    provider._keys, provider._keys_deadline = [], time() + 300
    assert provider.verify('code', transaction).subject == 'alice'
    assert sum(url.endswith('/keys') for _, url, _ in calls) == 1
    for endpoint in ('https://foreign.test/token', 'http://id.example.test/token',
                     'https://id.example.test/token?secret=private', 'https://user@id.example.test/token'):
        with pytest.raises(IdentityError):
            provider._endpoint(endpoint)


@pytest.mark.parametrize('attack', ['algorithm', 'signature', 'unknown_key'])
def test_algorithm_signature_and_unknown_key_fail_closed(oidc, attack):
    provider, transaction, claims, _, calls = oidc
    if attack == 'algorithm':
        token = jwt.encode(claims, 'synthetic-hmac-secret' * 3, algorithm='HS256', headers={'kid': 'key'})
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'foreign' if attack == 'unknown_key' else 'key'})
    provider.transport.token_override = token
    with pytest.raises(IdentityError) as caught:
        provider.verify('code', transaction)
    assert caught.value.code == 'unauthorized' and caught.value.__context__ is None
    if attack == 'unknown_key':
        assert sum(url.endswith('/keys') for _, url, _ in calls) == 2
