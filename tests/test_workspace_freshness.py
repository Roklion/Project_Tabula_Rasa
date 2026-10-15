"""Recent-login checks agree with the verified provider's bounded clock skew."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.infrastructure.postgres.workspaces import PostgresWorkspaceRepository


@pytest.mark.parametrize('age,allowed', [(-61, False), (-60, True), (-0.5, True),
                                        (0, True), (300, True), (301, False)])
def test_workspace_recent_login_has_bounded_future_and_past_limits(age, allowed):
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    repository = PostgresWorkspaceRepository(None, clock=lambda: now)
    session = SimpleNamespace(verified_email='synthetic@example.test',
                              authenticated_at=now - timedelta(seconds=age))
    if allowed:
        repository._require_fresh(session)
    else:
        with pytest.raises(IdentityError, match='reauthentication_required'):
            repository._require_fresh(session)


def test_workspace_recent_login_still_requires_verified_email():
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    repository = PostgresWorkspaceRepository(None, clock=lambda: now)
    for session in (None, SimpleNamespace(verified_email='', authenticated_at=now)):
        with pytest.raises(IdentityError, match='reauthentication_required'):
            repository._require_fresh(session)
