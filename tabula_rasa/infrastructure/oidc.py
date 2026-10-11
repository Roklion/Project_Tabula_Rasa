"""Bounded OIDC code/PKCE verification; provider material never reaches services."""

from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from hmac import compare_digest
import json
from math import isfinite
from threading import RLock
from time import time
from urllib.parse import quote, urlencode, urlsplit

import jwt
import requests

from tabula_rasa.application.identity import IdentityError, VerifiedIdentity


@dataclass(frozen=True)
class OidcSettings:
    issuer: str
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    session_generation: str = field(repr=False)
    environment: str
    public_origin: str

    def __post_init__(self):
        url = urlsplit(self.issuer)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.query or url.fragment or self.issuer.endswith('/')
                or not self.client_id or not self.client_secret or len(self.session_generation) < 32):
            raise ValueError('Invalid identity configuration.')

    @property
    def callback(self):
        return self.public_origin + '/api/v1/auth/callback'

    @property
    def configuration_hash(self):
        # A change to issuer/client/secret/operator generation revokes this
        # environment's sessions. Fingerprint remains server-only.
        return sha256(json.dumps([self.environment, self.issuer, self.client_id, self.client_secret,
                                  self.session_generation, self.public_origin]).encode()).hexdigest()

    @classmethod
    def from_environment(cls, settings, environment):
        return cls(*(environment.get('TABULA_RASA_' + key, '') for key in
                     ('OIDC_ISSUER', 'OIDC_CLIENT_ID', 'OIDC_CLIENT_SECRET', 'SESSION_GENERATION')),
                   settings.environment, settings.public_origin)


class OidcProvider:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.transport = transport or requests.Session()
        if transport is None:
            self.transport.trust_env = False
        self._lock = RLock()
        self._metadata = None
        self._keys = None
        self._metadata_deadline = self._keys_deadline = 0

    def close(self):
        self.transport.close()

    def _endpoint(self, url):
        expected, actual = urlsplit(self.settings.issuer), urlsplit(url)
        if (actual.scheme != 'https' or actual.netloc != expected.netloc or actual.username or actual.password
                or actual.query or actual.fragment):
            raise IdentityError('unavailable')
        return url

    def _json(self, method, url, **kwargs):
        try:
            with self.transport.request(method, self._endpoint(url), timeout=(3, 5), allow_redirects=False,
                                        stream=True, **kwargs) as response:
                if response.status_code != 200:
                    raise ValueError('provider_failure')
                body = bytearray()
                for chunk in response.iter_content(8192):
                    body.extend(chunk)
                    if len(body) > 262144:
                        raise ValueError('provider_failure')
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise ValueError('provider_failure')
                return result
        except Exception:
            pass
        raise IdentityError('unavailable')

    def metadata(self):
        with self._lock:
            if self._metadata is None or time() >= self._metadata_deadline:
                data = self._json('GET', self.settings.issuer + '/.well-known/openid-configuration')
                if data.get('issuer') != self.settings.issuer:
                    raise IdentityError('unavailable')
                for key in ('authorization_endpoint', 'token_endpoint', 'jwks_uri', 'userinfo_endpoint'):
                    if not isinstance(data.get(key), str):
                        raise IdentityError('unavailable')
                    self._endpoint(data[key])
                if ('RS256' not in data.get('id_token_signing_alg_values_supported', [])
                        or 'S256' not in data.get('code_challenge_methods_supported', [])
                        or 'client_secret_basic' not in data.get('token_endpoint_auth_methods_supported', [])):
                    raise IdentityError('unavailable')
                self._metadata, self._metadata_deadline = data, time() + 300
            return self._metadata

    def authorization_url(self, transaction):
        challenge = urlsafe_b64encode(sha256(transaction.verifier.encode('ascii')).digest()).rstrip(b'=').decode()
        return self.metadata()['authorization_endpoint'] + '?' + urlencode({
            'client_id': self.settings.client_id, 'redirect_uri': self.settings.callback,
            'response_type': 'code', 'scope': 'openid email profile', 'state': transaction.state,
            'nonce': transaction.nonce, 'code_challenge': challenge, 'code_challenge_method': 'S256', 'max_age': '0',
        })

    def _key(self, token):
        header = jwt.get_unverified_header(token)
        if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str) or len(header['kid']) > 256:
            raise IdentityError('unauthorized')
        with self._lock:
            for refresh in range(2):
                if refresh or self._keys is None or time() >= self._keys_deadline:
                    data = self._json('GET', self.metadata()['jwks_uri'])
                    if not isinstance(data.get('keys'), list) or len(data['keys']) > 100:
                        raise IdentityError('unavailable')
                    self._keys, self._keys_deadline = data['keys'], time() + 300
                matches = [key for key in self._keys if isinstance(key, dict) and key.get('kid') == header['kid']
                           and key.get('kty') == 'RSA' and key.get('use', 'sig') == 'sig'
                           and key.get('alg', 'RS256') == 'RS256' and 'verify' in key.get('key_ops', ['verify'])]
                if len(matches) == 1:
                    return jwt.PyJWK.from_dict(matches[0], algorithm='RS256').key
        raise IdentityError('unauthorized')

    def verify(self, code, transaction):
        try:
            if not isinstance(code, str) or not 1 <= len(code) <= 4096:
                raise IdentityError('unauthorized')
            data = self._json('POST', self.metadata()['token_endpoint'],
                auth=(quote(self.settings.client_id, safe=''), quote(self.settings.client_secret, safe='')),
                data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': self.settings.callback,
                      'code_verifier': transaction.verifier})
            token, access = data.get('id_token'), data.get('access_token')
            if (not isinstance(token, str) or len(token) > 32768 or not isinstance(access, str)
                    or not access or len(access) > 32768 or data.get('token_type', '').lower() != 'bearer'):
                raise IdentityError('unauthorized')
            claims = jwt.decode(token, self._key(token), algorithms=['RS256'], issuer=self.settings.issuer,
                audience=self.settings.client_id, leeway=60,
                options={'require': ['iss', 'sub', 'aud', 'exp', 'iat', 'nonce', 'auth_time']})
            for key in ('exp', 'iat', 'auth_time', 'nbf'):
                if key in claims and (type(claims[key]) not in {int, float} or not isfinite(claims[key])):
                    raise IdentityError('unauthorized')
            now = time()
            if (not isinstance(claims['sub'], str) or not claims['sub'].strip() or len(claims['sub']) > 1024
                    or not isinstance(claims['nonce'], str)
                    or not compare_digest(claims['nonce'].encode(), transaction.nonce.encode())
                    or not now - 300 <= claims['auth_time'] <= now + 60
                    or (isinstance(claims['aud'], list) and len(claims['aud']) > 1 and 'azp' not in claims)
                    or ('azp' in claims and claims['azp'] != self.settings.client_id)):
                raise IdentityError('unauthorized')
            if 'at_hash' in claims:
                expected = urlsafe_b64encode(sha256(access.encode('ascii')).digest()[:16]).rstrip(b'=').decode()
                if claims['at_hash'] != expected:
                    raise IdentityError('unauthorized')
            info = self._json('GET', self.metadata()['userinfo_endpoint'], headers={'Authorization': 'Bearer ' + access})
            if (info.get('sub') != claims['sub'] or info.get('email_verified') is not True
                    or not isinstance(info.get('email'), str) or not info['email'].strip() or len(info['email']) > 320):
                raise IdentityError('unauthorized')
            name = info.get('name', '')
            if not isinstance(name, str) or len(name) > 500:
                name = ''
            return VerifiedIdentity(self.settings.issuer, claims['sub'], info['email'], name,
                                    datetime.fromtimestamp(claims['auth_time'], timezone.utc))
        except IdentityError as error:
            code = error.code
        except Exception:
            code = 'unauthorized'
        raise IdentityError(code)
