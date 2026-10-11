"""One durable session validator shared by identity and entity routes."""

from datetime import datetime, timedelta, timezone
from dataclasses import replace
from hashlib import sha256
import secrets

from sqlalchemy import text

from tabula_rasa.application.identity import AuthenticatedSession, IdentityError, LoginTransaction
from .control_plane import PostgresIdentityRepository, entity_access, identity_operation


def credential_hash(value):
    if not isinstance(value, str) or not 32 <= len(value) <= 256 or not value.isascii():
        raise IdentityError('unauthorized')
    return sha256(value.encode('ascii')).hexdigest()


class PostgresSessionRepository:
    def __init__(self, database, environment, configuration_hash, *, clock=None):
        self.database = database
        self.environment = environment
        self.configuration_hash = configuration_hash
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.identity = PostgresIdentityRepository(database)

    def configure(self):
        # Run at explicit named-runtime startup. Old workers cannot validate or
        # issue under the old epoch after a coordinated configuration rotation.
        with identity_operation(self.database) as connection:
            connection.execute(text('''INSERT INTO identity_environments(environment,configuration_hash) VALUES (:env,:hash)
                ON CONFLICT (environment) DO UPDATE SET configuration_hash=EXCLUDED.configuration_hash,
                epoch=identity_environments.epoch+1
                WHERE identity_environments.configuration_hash<>EXCLUDED.configuration_hash'''),
                {'env': self.environment, 'hash': self.configuration_hash})

    def _epoch(self, connection):
        epoch = connection.scalar(text('''SELECT epoch FROM identity_environments
            WHERE environment=:env AND configuration_hash=:hash FOR SHARE'''),
            {'env': self.environment, 'hash': self.configuration_hash})
        if epoch is None:
            raise IdentityError('unauthorized')
        return epoch

    def begin_login(self, return_path, previous=None):
        if return_path not in {'/', '/onboarding'}:
            raise IdentityError('forbidden')
        raw = secrets.token_urlsafe(32)
        transaction = LoginTransaction(secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48), return_path)
        with identity_operation(self.database) as connection:
            epoch = self._epoch(connection)
            if previous:
                try:
                    previous_hash = credential_hash(previous)
                except IdentityError:
                    previous_hash = None
                connection.execute(text('DELETE FROM identity_login_transactions WHERE credential_hash=:hash AND environment=:env'),
                    {'hash': previous_hash, 'env': self.environment})
            connection.execute(text('''INSERT INTO identity_login_transactions
                (credential_hash,environment,environment_epoch,state,nonce,verifier,return_path,expires_at)
                VALUES (:hash,:env,:epoch,:state,:nonce,:verifier,:path,:expiry)'''),
                {'hash': credential_hash(raw), 'env': self.environment, 'epoch': epoch, 'state': transaction.state,
                 'nonce': transaction.nonce, 'verifier': transaction.verifier, 'path': return_path,
                 'expiry': self.clock() + timedelta(minutes=5)})
        return raw, transaction

    def consume_login(self, raw, state):
        with identity_operation(self.database) as connection:
            row = connection.execute(text('''UPDATE identity_login_transactions SET consumed_at=:now
                WHERE credential_hash=:hash AND state=:state AND environment=:env
                AND environment_epoch=:epoch AND consumed_at IS NULL AND expires_at>:now
                RETURNING state,nonce,verifier,return_path'''),
                {'hash': credential_hash(raw), 'state': state, 'env': self.environment,
                 'epoch': self._epoch(connection), 'now': self.clock()}).mappings().first()
            if row is None:
                raise IdentityError('unauthorized')
            return LoginTransaction(**row)

    def issue(self, identity, previous=None):
        raw, csrf, cache = (secrets.token_urlsafe(32) for _ in range(3))
        now = self.clock()
        with identity_operation(self.database) as connection:
            epoch = self._epoch(connection)
            user = self.identity.resolve_user(identity)
            binding = connection.scalar(text('SELECT id FROM identity_bindings WHERE user_id=:user'), {'user': user.id})
            choices = entity_access(connection, user.id)
            selected = choices[0] if choices else None
            if previous:
                try:
                    previous_hash = credential_hash(previous)
                except IdentityError:
                    previous_hash = None
                connection.execute(text('''UPDATE identity_sessions SET revoked_at=:now
                    WHERE credential_hash=:hash AND environment=:env'''),
                    {'hash': previous_hash, 'env': self.environment, 'now': now})
            connection.execute(text('''INSERT INTO identity_sessions(credential_hash,environment,environment_epoch,user_id,
                binding_id,user_epoch,csrf_token,cache_id,created_at,authenticated_at,idle_expires_at,absolute_expires_at,
                organization_id,entity_id) VALUES (:hash,:env,:epoch,:user,:binding,:user_epoch,:csrf,:cache,:now,:auth,
                :idle,:absolute,:org,:entity)'''),
                {'hash': credential_hash(raw), 'env': self.environment, 'epoch': epoch, 'user': user.id,
                 'binding': binding, 'user_epoch': user.session_epoch, 'csrf': csrf, 'cache': cache, 'now': now,
                 'auth': identity.authenticated_at, 'idle': now + timedelta(minutes=30), 'absolute': now + timedelta(hours=12),
                 'org': selected.organization_id if selected else None, 'entity': selected.entity_id if selected else None})
        return raw, AuthenticatedSession(user.id, cache, csrf, identity.authenticated_at,
                                         now + timedelta(hours=12), selected)

    def validate(self, raw, *, foreground=False):
        now = self.clock()
        with identity_operation(self.database) as connection:
            row = connection.execute(text('''SELECT s.* FROM identity_sessions s
                JOIN identity_users u ON u.id=s.user_id AND u.state='active' AND u.session_epoch=s.user_epoch
                JOIN identity_bindings b ON b.id=s.binding_id AND b.user_id=s.user_id
                WHERE s.credential_hash=:hash AND s.environment=:env AND s.environment_epoch=:epoch
                AND s.revoked_at IS NULL AND s.idle_expires_at>:now AND s.absolute_expires_at>:now FOR UPDATE OF s'''),
                {'hash': credential_hash(raw), 'env': self.environment, 'epoch': self._epoch(connection), 'now': now}).mappings().first()
            if row is None:
                raise IdentityError('unauthorized')
            selected = next((item for item in entity_access(connection, row['user_id'])
                             if item.entity_id == row['entity_id'] and item.organization_id == row['organization_id']), None)
            if foreground:
                connection.execute(text('UPDATE identity_sessions SET idle_expires_at=:expiry WHERE credential_hash=:hash'),
                    {'expiry': min(now + timedelta(minutes=30), row['absolute_expires_at']), 'hash': row['credential_hash']})
            return AuthenticatedSession(row['user_id'], row['cache_id'], row['csrf_token'], row['authenticated_at'],
                                        row['absolute_expires_at'], selected)

    def revoke(self, raw):
        with identity_operation(self.database) as connection:
            connection.execute(text('''UPDATE identity_sessions SET revoked_at=:now
                WHERE credential_hash=:hash AND environment=:env'''),
                {'hash': credential_hash(raw), 'env': self.environment, 'now': self.clock()})

    def select(self, raw, entity_id):
        with identity_operation(self.database):
            session = self.validate(raw)
            selected = next((item for item in self.identity.allowed_entities(session.user_id) if item.entity_id == entity_id), None)
            if selected is None:
                raise IdentityError('forbidden')
            with self.database.transaction() as connection:
                connection.execute(text('''UPDATE identity_sessions SET organization_id=:org,entity_id=:entity
                    WHERE credential_hash=:hash'''),
                    {'org': selected.organization_id, 'entity': selected.entity_id, 'hash': credential_hash(raw)})
        return replace(session, selected=selected)
