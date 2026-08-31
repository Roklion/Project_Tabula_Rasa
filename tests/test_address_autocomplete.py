"""State-contract tests for the browser address component adapter."""

from tabula_rasa.address_autocomplete import (
    AddressSelection,
    _HTML,
    _JS,
    browser_api_key_from_secrets,
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
    assert "element.addEventListener('input'" not in _JS
    assert "setTriggerValue('failed', true)" not in _JS
    assert "window.__tabulaRasaPlacesPromise = null;" in _JS
    assert "if (failedScript) failedScript.remove();" in _JS


def test_switching_back_to_google_mode_unhides_the_autocomplete_host() -> None:
    assert "manual.hidden = true;\n    host.hidden = false;" in _JS


def test_inline_attribution_is_hidden_for_manual_mode() -> None:
    assert '<small id="tr-address-attribution" hidden>Google Maps</small>' in _HTML
    assert "const attribution = parentElement.querySelector('#tr-address-attribution');" in _JS
    assert "function hideAttribution()" in _JS
    assert "hideAttribution();" in _JS
    assert "await loadMaps();\n      showAttribution();" in _JS


def test_browser_key_fails_closed_when_routes_key_is_reused() -> None:
    assert browser_api_key_from_secrets(
        {
            "google_maps": {
                "browser_api_key": " browser-key ",
                "routes_api_key": "routes-key",
            }
        }
    ) == "browser-key"
    assert (
        browser_api_key_from_secrets(
            {
                "google_maps": {
                    "browser_api_key": "reused-key",
                    "routes_api_key": " reused-key ",
                }
            }
        )
        is None
    )


def test_browser_key_rejects_non_ascii_key_material() -> None:
    assert (
        browser_api_key_from_secrets(
            {
                "google_maps": {
                    "browser_api_key": "browser-kéy",
                    "routes_api_key": "routes-key",
                }
            }
        )
        is None
    )
