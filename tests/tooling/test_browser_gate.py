"""A required native browser gate cannot silently skip its database coverage."""

import pytest

from tests.postgres.conftest import empty_database


@pytest.mark.parametrize('required', [False, True])
def test_missing_explicit_test_target_skips_only_outside_required_gate(monkeypatch, required):
    monkeypatch.delenv('TABULA_RASA_TEST_DATABASE_URL', raising=False)
    monkeypatch.setenv('TABULA_RASA_REQUIRE_BROWSER_TESTS', '1' if required else '0')
    expected = pytest.fail.Exception if required else pytest.skip.Exception
    with pytest.raises(expected, match='TABULA_RASA_TEST_DATABASE_URL'):
        next(empty_database.__wrapped__())
