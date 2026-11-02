"""The reversible state contract, independent of adapters and policy proposals."""

import pytest

from tabula_rasa.application.customer_lifecycle import transition
from tabula_rasa.application.identity import IdentityError


@pytest.mark.parametrize('current,action,version,expected,result', [
    ('pending', 'confirm', 1, 1, True), ('confirmed', 'confirm', 2, 1, False),
    ('pending', 'cancel', 1, 1, True), ('confirmed', 'cancel', 2, 2, True),
    ('cancelled', 'cancel', 3, 2, False),
])
def test_transition_and_response_loss_replay(current, action, version, expected, result):
    assert transition(current, action, version, expected) is result


@pytest.mark.parametrize('current,action,version,expected,code', [
    ('pending', 'confirm', 2, 1, 'stale'),
    ('cancelled', 'confirm', 3, 3, 'conflict'),
    ('confirmed', 'delete', 2, 2, 'validation'),
])
def test_stale_conflicting_and_destructive_commands_stop(current, action, version, expected, code):
    with pytest.raises(IdentityError, match=code):
        transition(current, action, version, expected)
