from __future__ import annotations


from tabula_rasa.submission_guard import is_recent_duplicate, mark_completed


class TestSubmissionGuard:
    def test_only_successfully_marked_identical_payload_is_suppressed(self) -> None:
        state: dict = {}
        payload = {"amount": 10, "account": "checking"}
        assert not is_recent_duplicate(state, "transaction", payload, now=1)

        mark_completed(state, "transaction", payload, now=2)

        assert is_recent_duplicate(state, "transaction", payload, now=3)
        assert not is_recent_duplicate(
            state,
            "transaction",
            {"amount": 11, "account": "checking"},
            now=3,
        )

    def test_identical_payload_is_allowed_after_window(self) -> None:
        state: dict = {}
        payload = {"name": "Checking"}
        mark_completed(state, "account", payload, now=1)
        assert not is_recent_duplicate(
            state, "account", payload, window_seconds=10, now=12
        )
