"""State-contract tests for the browser address component adapter."""

from types import SimpleNamespace

import streamlit as st

import tabula_rasa.address_autocomplete as address_module
from tabula_rasa.address_autocomplete import (
    AddressSelection,
    _COMPONENT_STATE_NAMES,
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
    assert "setStateValue('failed', true)" in _JS
    assert "setStateValue('provider_failed'" not in _JS
    assert "apiKeyConfigured: Boolean(data.apiKey)" in _JS
    assert "console.error('[Tabula Rasa] Address autocomplete failed'" in _JS
    assert "'$1[redacted]'" in _JS
    assert "reportFailure('Google place selection', error);" in _JS
    assert "maps.importLibrary('places')" in _JS
    assert "maps.importLibrary = (library, ...args) =>" in _JS
    assert "google.maps.__tabulaRasaMapsLoaded" in _JS
    assert "const {PlaceAutocompleteElement} = placesLibrary || {};" in _JS
    assert "new google.maps.places.PlaceAutocompleteElement" not in _JS
    assert "if (manualMode) { showManual('Enter an address manually.'); return; }" in _JS
    assert "manualInput.onchange = () => emit('manual', manualInput.value.trim());" in _JS
    assert "manualInput.oninput" not in _JS
    assert "element.addEventListener('input'" not in _JS
    assert "setTriggerValue('failed', true)" not in _JS
    assert "window.__tabulaRasaPlacesPromise = null;" in _JS
    assert "if (failedScript) failedScript.remove();" in _JS


def test_switching_back_to_google_mode_unhides_the_autocomplete_host() -> None:
    assert "manual.hidden = true;\n    host.hidden = false;" in _JS


def test_setup_failure_clears_previous_place_selection() -> None:
    assert (
        "clearFailedMapsLoad();\n"
        "      selectedDisplay = '';\n"
        "      const widget = host.querySelector('gmp-place-autocomplete');\n"
        "      emit('changed', (widget && widget.value) || '');\n"
        "      showManual('Google address suggestions are unavailable.');"
    ) in _JS


def test_failed_maps_load_button_retries_google_mode() -> None:
    assert (
        "showManual('Google address suggestions are unavailable.');\n"
        "      manualMode = true;\n"
        "      providerFailed = true;\n"
        "      setStateValue('manual_mode', true);\n"
        "      setStateValue('failed', true);\n"
        "      manualButton.onclick = selectGoogleMode;"
    ) in _JS


def test_provider_error_clears_previous_place_selection() -> None:
    assert (
        "selectedDisplay = '';\n"
        "        emit('changed', element.value || '');\n"
        "        showManual('Google address suggestions are unavailable.');"
    ) in _JS


def test_google_provider_errors_switch_to_manual_mode() -> None:
    assert "element.addEventListener('gmp-error', () => {" in _JS
    assert (
        "manualMode = true;\n"
        "        providerFailed = true;\n"
        "        setStateValue('manual_mode', true);\n"
        "        setStateValue('failed', true);\n"
        "        selectedDisplay = '';\n"
        "        emit('changed', element.value || '');\n"
        "        showManual('Google address suggestions are unavailable.');"
    ) in _JS


def test_manual_mode_does_not_mark_provider_as_failed() -> None:
    assert "manualMode = true;\n    providerFailed = false;" in _JS
    assert "setStateValue('manual_mode', true);\n    setStateValue('failed', false);" in _JS


def test_component_defaults_only_use_declared_state_names(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_component(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(address_module, "_component", fake_component)
    monkeypatch.setattr(st, "session_state", {})

    address_module.address_autocomplete("Address", key="address", api_key="key")
    defaults = captured["default"]

    assert isinstance(defaults, dict)
    assert set(defaults) <= _COMPONENT_STATE_NAMES
    assert set(defaults) == {"failed", "manual_mode"}


def test_manual_mode_wins_if_selected_while_maps_loads() -> None:
    assert (
        "const placesLibrary = await loadMaps();\n"
        "      if (manualMode) {\n"
        "        showManual('Enter an address manually.');\n"
        "        return;\n"
        "      }"
    ) in _JS


def test_inline_attribution_is_hidden_for_manual_mode() -> None:
    assert (
        '<small id="tr-address-attribution" class="tr-google-maps-attribution"'
        in _HTML
    )
    assert 'translate="no"' in _HTML
    assert "Google Maps" in _HTML
    assert "const attribution = parentElement.querySelector('#tr-address-attribution');" in _JS
    assert "function hideAttribution()" in _JS
    assert "hideAttribution();" in _JS
    assert (
        "const placesLibrary = await loadMaps();\n"
        "      if (manualMode) {\n"
        "        showManual('Enter an address manually.');\n"
        "        return;\n"
        "      }\n"
        "      showAttribution();"
    ) in _JS


def test_google_selection_cannot_be_overwritten_by_followup_change_event() -> None:
    assert "let selectedDisplay = '';" in _JS
    assert (
        "if (suppressInput || (selectedDisplay && element.value === selectedDisplay))"
        in _JS
    )


def test_inline_attribution_css_honors_hidden_state() -> None:
    from tabula_rasa.address_autocomplete import _CSS

    assert ".tr-google-maps-attribution[hidden] { display: none; }" in _CSS
    assert "selectedDisplay = display;" in _JS
    assert "finally {\n          suppressInput = false;\n        }" in _JS


def test_google_selection_requests_only_transient_place_id() -> None:
    assert "await place.fetchFields({fields: ['id']});" in _JS
    assert "formattedAddress" not in _JS
    assert "displayName" not in _JS
    assert "durable ledger text is collected separately" in _JS


def test_provider_fallback_preserves_current_widget_text() -> None:
    assert (
        "const widget = host.querySelector('gmp-place-autocomplete');\n"
        "    manualInput.value = initialValue ||\n"
        "      (widget && widget.value) || data.value || '';"
    ) in _JS


def test_address_controls_use_streamlit_visual_tokens() -> None:
    from tabula_rasa.address_autocomplete import _CSS

    assert "var(--st-secondary-background-color)" in _CSS
    assert "var(--st-widget-border-color" in _CSS
    assert "#tr-address-host > gmp-place-autocomplete" in _CSS
    assert ".tr-address button:focus-visible" in _CSS
    assert ".tr-address button:disabled" in _CSS
    assert "font-weight: 600;" in _CSS


def test_google_autocomplete_prediction_parts_use_theme_contrast() -> None:
    from tabula_rasa.address_autocomplete import _CSS

    assert "color-scheme: light;" in _CSS
    assert "::part(prediction-list)" in _CSS
    assert "::part(prediction-item-main-text)" in _CSS
    assert "::part(prediction-item-secondary-text)" in _CSS
    assert "background-color: var(--st-background-color);" in _CSS
    assert "color: var(--st-text-color);" in _CSS


def test_google_autocomplete_matches_streamlit_control_dimensions() -> None:
    from tabula_rasa.address_autocomplete import _CSS

    assert "height: 2.5rem;" in _CSS
    assert "min-height: 2.5rem;" in _CSS
    assert "padding: .5rem .75rem;" in _CSS
    assert "border-radius: 6px;" in _CSS
    assert "min-height: 36px;" in _CSS


def test_google_autocomplete_input_has_a_complete_theme_border() -> None:
    from tabula_rasa.address_autocomplete import _CSS

    assert "::part(input)" in _CSS
    assert "border: 1px solid var(--st-widget-border-color, rgba(49, 51, 63, .2));" in _CSS
    assert "border-radius: 6px;" in _CSS
    assert "::part(input):focus" in _CSS


def test_failed_place_details_clear_the_previous_selection() -> None:
    catch_emission = (
        "selectedDisplay = '';\n"
        "          version += 1;\n"
        "          setTriggerValue('changed', {\n"
        "            display_text: element.value || '', place_id: '', version: version\n"
        "          });"
    )
    assert catch_emission in _JS


def test_python_attribution_is_explicit_and_not_translated(monkeypatch) -> None:
    import streamlit as st

    rendered: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        st,
        "markdown",
        lambda body, **kwargs: rendered.append(
            (body, kwargs.get("unsafe_allow_html", False))
        ),
    )
    from tabula_rasa.address_autocomplete import render_google_maps_attribution

    render_google_maps_attribution()

    assert rendered == [
        (
            '<div class="tr-google-maps-attribution" role="note" translate="no" '
            'aria-label="Google Maps attribution">Google Maps</div>',
            True,
        )
    ]


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


def test_browser_key_fails_closed_for_non_mapping_secrets() -> None:
    assert browser_api_key_from_secrets(None) is None  # type: ignore[arg-type]
