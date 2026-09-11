from datetime import date

from tabula_rasa.page_renderers.transactions.recurring import _safe_date, _safe_interval


def test_recurring_editor_uses_safe_defaults_for_corrupt_schedule_fields() -> None:
    assert _safe_interval("not-a-number") == 1
    assert _safe_interval("0") == 1
    assert _safe_date("not-a-date", date(2026, 9, 11)) == date(2026, 9, 11)
    assert _safe_date("") is None
