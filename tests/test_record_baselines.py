import pytest

from tabula_rasa.application.baselines import RecordBaseline
from tabula_rasa.errors import StorageValidationError


def test_portable_baseline_round_trips_without_provider_types():
    baseline = RecordBaseline("entity α", "entry", "generated-id", "lifetime", 42)
    assert RecordBaseline.decode(baseline.encode()) == baseline


@pytest.mark.parametrize("token", [None, "", "v2.abc", "v1.@@@", "v1.e30", "v1.W10", "v1.WyJhIl0"])
def test_invalid_tokens_raise_safe_errors(token):
    with pytest.raises(StorageValidationError, match="Invalid loaded-record baseline") as caught:
        RecordBaseline.decode(token)
    assert caught.value.__context__ is None


@pytest.mark.parametrize("version", [True, 0, -1, "1", 2**63])
def test_invalid_versions_are_rejected(version):
    with pytest.raises(StorageValidationError):
        RecordBaseline("entity", "entry", "id", "lifetime", version)
