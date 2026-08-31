"""State-contract tests for the browser address component adapter."""

from tabula_rasa.address_autocomplete import (
    AddressSelection,
    _JS,
    _latest_selection,
    _region_code,
)


def test_latest_component_signal_wins_across_event_types() -> None:
    typed = AddressSelection("10 Main", "", 3)
    selected = AddressSelection("10 Main Street", "place-10", 4)

    assert _latest_selection(typed, selected) == selected

    changed_again = AddressSelection("10 Main Street Apt", "", 5)
    assert _latest_selection(changed_again, selected) == changed_again


def test_autocomplete_region_requires_two_ascii_letters() -> None:
    assert _region_code(" US ") == "us"
    assert _region_code(None) == ""
    assert _region_code("usa") == ""
    assert _region_code("éu") == ""


def test_manual_fallback_persists_without_rerunning_per_keystroke() -> None:
    assert "setStateValue('manual_mode', true)" in _JS
    assert "if (manualMode) { showManual('Enter an address manually.'); return; }" in _JS
    assert "manualInput.onchange = () => emit('manual', manualInput.value.trim());" in _JS
    assert "manualInput.oninput" not in _JS
