"""Opaque loaded baselines cross the shared reference-service boundary unchanged."""


import pytest

from tabula_rasa.application import AccountService, CategoryService
from tabula_rasa.application.baselines import RecordBaseline


@pytest.mark.parametrize("service_type", [AccountService, CategoryService])
def test_reference_service_passes_the_opaque_baseline_separately_without_reads(service_type):
    token = RecordBaseline("alpha", "account" if service_type is AccountService else "category", "id", "life", 1).encode()
    expected = {"baseline": token}

    class Repository:
        def update(self, identity, *, changes, expected=None):
            assert identity == "id"
            assert changes == {"name": "New name"}
            assert expected is supplied
            return {"id": identity, "baseline": "new-token"}

    supplied = expected
    result = service_type(Repository()).update("id", name=" New name ", expected=supplied)
    assert result["baseline"] == "new-token"
