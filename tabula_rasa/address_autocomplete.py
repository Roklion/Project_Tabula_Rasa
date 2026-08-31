"""Small, dependency-free Google Places address input.

The Maps JavaScript API is deliberately loaded by the component in the browser.
This keeps Google credentials out of Python and makes the page straightforward
to test: when no key is configured, the function is an ordinary Streamlit
text input and returns an address without a Place ID.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import secrets
from typing import Any

import streamlit as st


@dataclass(frozen=True)
class AddressSelection:
    """The stable value returned by :func:`address_autocomplete`.

    ``version`` increments whenever a user makes a new selection (or changes
    manual text).  Callers can use it as a cheap stale-result guard instead of
    comparing browser component values.
    """

    display_text: str = ""
    place_id: str = ""
    version: int = 0

    def __getitem__(self, key: str) -> Any:
        return {
            "display_text": self.display_text,
            "place_id": self.place_id,
            "version": self.version,
        }[key]

    def as_dict(self) -> dict[str, Any]:
        return {
            "display_text": self.display_text,
            "place_id": self.place_id,
            "version": self.version,
        }


_HTML = """
<div class="tr-address" role="group">
  <label id="tr-address-label"></label>
  <div id="tr-address-host"></div>
  <div id="tr-address-manual" hidden>
    <input id="tr-address-input" type="text" autocomplete="street-address" />
  </div>
  <button id="tr-address-manual-button" type="button" hidden>
    Enter address manually
  </button>
  <small id="tr-address-status" role="status" aria-live="polite"></small>
  <small id="tr-address-attribution" hidden>Google Maps</small>
</div>
"""

_CSS = """
.tr-address { display: flex; flex-direction: column; gap: .25rem; }
.tr-address label { font-weight: 500; }
.tr-address small { color: var(--st-text-color); opacity: .75; }
.tr-address button { align-self: flex-start; }
.tr-address input { width: 100%; box-sizing: border-box; }
"""

_JS = """
export default function(component) {
  const {data, parentElement, setStateValue, setTriggerValue} = component;
  const label = parentElement.querySelector('#tr-address-label');
  const host = parentElement.querySelector('#tr-address-host');
  const manual = parentElement.querySelector('#tr-address-manual');
  const manualInput = parentElement.querySelector('#tr-address-input');
  const manualButton = parentElement.querySelector('#tr-address-manual-button');
  const status = parentElement.querySelector('#tr-address-status');
  const attribution = parentElement.querySelector('#tr-address-attribution');
  label.textContent = data.label || 'Address';
  manualInput.setAttribute('aria-label', data.label || 'Address');
  let version = Number(data.version || 0);
  let manualMode = data.manualMode === true;
  let suppressInput = false;

  function showAttribution() {
    attribution.hidden = false;
  }
  function hideAttribution() {
    attribution.hidden = true;
  }

  function emit(name, value) {
    version += 1;
    setTriggerValue(name, {
      display_text: value || '', place_id: '', version: version
    });
  }
  function showManual(message) {
    hideAttribution();
    host.hidden = true;
    manual.hidden = false;
    manualButton.hidden = false;
    manualButton.textContent = 'Use Google suggestions';
    status.textContent = message || 'Google suggestions are unavailable.';
    manualInput.value = data.value || '';
    manualInput.onchange = () => emit('manual', manualInput.value.trim());
    manualInput.focus();
  }
  function selectManualMode() {
    manualMode = true;
    setStateValue('manual_mode', true);
    showManual('Enter an address manually.');
  }
  function selectGoogleMode() {
    manualMode = false;
    setStateValue('manual_mode', false);
    setup();
  }
  function loadMaps() {
    if (window.google && window.google.maps && window.google.maps.places) {
      return Promise.resolve();
    }
    if (window.__tabulaRasaPlacesPromise) return window.__tabulaRasaPlacesPromise;
    window.__tabulaRasaPlacesPromise = new Promise((resolve, reject) => {
      const existing = document.querySelector('script[data-tabula-rasa-places]');
      if (existing) {
        existing.addEventListener('load', resolve, {once: true});
        existing.addEventListener('error', reject, {once: true});
        return;
      }
      const script = document.createElement('script');
      script.src = 'https://maps.googleapis.com/maps/api/js?key=' +
        encodeURIComponent(data.apiKey) + '&loading=async&libraries=places';
      script.async = true;
      script.defer = true;
      script.dataset.tabulaRasaPlaces = 'true';
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
    return window.__tabulaRasaPlacesPromise;
  }
  function clearFailedMapsLoad() {
    if (window.google && window.google.maps && window.google.maps.places) return;
    const failedScript = document.querySelector('script[data-tabula-rasa-places]');
    if (failedScript) failedScript.remove();
    window.__tabulaRasaPlacesPromise = null;
  }
  async function setup() {
    if (manualMode) { showManual('Enter an address manually.'); return; }
    if (!data.apiKey) { showManual('Enter an address manually.'); return; }
    manual.hidden = true;
    host.hidden = false;
    manualButton.hidden = false;
    manualButton.textContent = 'Enter address manually';
    status.textContent = 'Loading Google address suggestions…';
    try {
      await loadMaps();
      showAttribution();
      const options = {
        includedPrimaryTypes: ['street_address', 'premise', 'establishment']
      };
      if (data.regionCode) options.includedRegionCodes = [data.regionCode];
      const element = new google.maps.places.PlaceAutocompleteElement(options);
      element.setAttribute('aria-label', data.label || 'Address');
      element.value = data.value || '';
      host.replaceChildren(element);
      status.textContent = 'Start typing to choose a Google-verified address.';
      // PlaceAutocompleteElement owns the Google session lifecycle. Do not
      // create a parallel token here (that can result in duplicate billing).
      element.addEventListener('change', () => {
        if (suppressInput) return;
        version += 1;
        setTriggerValue('changed', {
          display_text: element.value || '', place_id: '', version: version
        });
      });
      element.addEventListener('gmp-select', async (event) => {
        status.textContent = 'Loading selected address…';
        try {
          const prediction = event.placePrediction;
          const place = prediction && prediction.toPlace ?
            prediction.toPlace() : null;
          if (!place) throw new Error('No place returned');
          await place.fetchFields({fields: ['id', 'displayName', 'formattedAddress']});
          const display = place.formattedAddress ||
            (place.displayName && place.displayName.text) || element.value || '';
          suppressInput = true;
          version += 1;
          setTriggerValue('selected', {
            display_text: display, place_id: place.id || '', version: version
          });
          suppressInput = false;
          status.textContent = 'Address selected.';
        } catch (error) {
          // Keep the browser error useful without exposing API details.
          status.textContent = 'The address could not be selected. Try again or enter it manually.';
          manualButton.hidden = false;
        }
      });
      element.addEventListener('gmp-error', () => {
        status.textContent = 'Google address suggestions are unavailable.';
        manualButton.hidden = false;
      });
      manualButton.onclick = () => {
        if (manual.hidden) selectManualMode();
        else selectGoogleMode();
      };
    } catch (error) {
      clearFailedMapsLoad();
      showManual('Google address suggestions are unavailable.');
      manualMode = true;
      setStateValue('manual_mode', true);
      manualButton.onclick = selectGoogleMode;
    }
  }
  // Keep manual entry available during script loading as well as after a
  // provider error; users should never be trapped behind a paid integration.
  manualButton.hidden = false;
  manualButton.textContent = 'Enter address manually';
  manualButton.onclick = selectManualMode;
  setup();
}
"""


_component = st.components.v2.component(
    "tabula_rasa_address_autocomplete",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def browser_api_key_from_secrets(
    secrets_mapping: Mapping[str, Any],
) -> str | None:
    """Return the browser key only when it is distinct from the Routes key.

    A mistakenly reused server key must fail closed instead of crossing the
    Streamlit component boundary. The Routes client can remain available, but
    autocomplete falls back to manual entry until two separate keys are set.
    """
    raw = secrets_mapping.get("google_maps")
    if not isinstance(raw, Mapping):
        return None
    browser_key = _clean_api_key(raw.get("browser_api_key"))
    if not browser_key:
        return None
    routes_key = _clean_api_key(raw.get("routes_api_key"))
    if routes_key and secrets.compare_digest(browser_key, routes_key):
        return None
    return browser_key


def _clean_api_key(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if (
        not value
        or len(value) > 256
        or not value.isascii()
        or any(ord(char) < 32 for char in value)
    ):
        return ""
    return value


def _mapping_selection(
    value: object, *, allow_empty: bool = False
) -> AddressSelection | None:
    if not isinstance(value, Mapping):
        return None
    display = str(value.get("display_text", "") or "").strip()
    if not display and not value.get("place_id") and not allow_empty:
        return None
    try:
        version = int(value.get("version", 0) or 0)
    except (TypeError, ValueError):
        version = 0
    return AddressSelection(
        display_text=display,
        place_id=str(value.get("place_id", "") or "").strip(),
        version=version,
    )


def _latest_selection(*values: AddressSelection | None) -> AddressSelection | None:
    """Return the newest component signal instead of trusting event type order."""
    candidates = [value for value in values if value is not None]
    return max(candidates, key=lambda value: value.version, default=None)


def _region_code(value: str | None) -> str:
    """Return a valid optional ISO-style two-letter autocomplete region."""
    normalized = str(value or "").strip().lower()
    return normalized if len(normalized) == 2 and normalized.isascii() and normalized.isalpha() else ""


def address_autocomplete(
    label: str,
    *,
    key: str,
    api_key: str | None = None,
    value: str = "",
    region_code: str | None = None,
) -> AddressSelection:
    """Render an address input and return its text, Place ID, and version.

    The native text-input path is intentional: local development, AppTest, and
    profiles without Maps configuration remain fully usable. A Place ID is
    only returned after a Google suggestion is explicitly selected.
    """
    state_key = f"{key}__selection"
    current = st.session_state.get(state_key)
    if not isinstance(current, AddressSelection):
        current = AddressSelection(display_text=value)

    if not api_key:
        typed = st.text_input(label, value=current.display_text, key=key)
        if typed != current.display_text:
            current = AddressSelection(
                display_text=typed,
                version=current.version + 1,
            )
            st.session_state[state_key] = current
        return current

    component_state = st.session_state.get(key)
    manual_mode = (
        bool(component_state.get("manual_mode", False))
        if isinstance(component_state, Mapping)
        else False
    )
    result = _component(
        data={
            "apiKey": api_key,
            "label": label,
            "value": current.display_text,
            "version": current.version,
            "regionCode": _region_code(region_code),
            "manualMode": manual_mode,
        },
        default={"manual_mode": manual_mode},
        key=key,
        on_selected_change=lambda: None,
        on_manual_change=lambda: None,
        on_changed_change=lambda: None,
        on_failed_change=lambda: None,
        on_manual_mode_change=lambda: None,
    )
    selected = _mapping_selection(getattr(result, "selected", None))
    manual = _mapping_selection(getattr(result, "manual", None), allow_empty=True)
    changed = _mapping_selection(getattr(result, "changed", None), allow_empty=True)
    # Trigger values may remain present after later component events. Compare
    # versions so a new selection beats older typed text, while later typing
    # still clears an older Place ID.
    next_value = _latest_selection(changed, selected, manual)
    if next_value is not None:
        current = next_value
        st.session_state[state_key] = current
    return current
