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


GOOGLE_MAPS_ATTRIBUTION_TEXT = "Google Maps"


def render_google_maps_attribution() -> None:
    """Render the required, legible attribution beside current Maps content."""
    st.markdown(
        '<div class="tr-google-maps-attribution" role="note" translate="no" '
        f'aria-label="{GOOGLE_MAPS_ATTRIBUTION_TEXT} attribution">'
        f"{GOOGLE_MAPS_ATTRIBUTION_TEXT}</div>",
        unsafe_allow_html=True,
    )


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
  <small id="tr-address-attribution" class="tr-google-maps-attribution"
    role="note" translate="no" aria-label="Google Maps attribution" hidden>Google Maps</small>
</div>
"""

_CSS = """
.tr-address {
  display: flex;
  flex-direction: column;
  gap: .25rem;
  color: var(--st-text-color);
  font: inherit;
  width: 100%;
}
.tr-address label { font-weight: 500; }
.tr-address small { color: var(--st-text-color); }
.tr-google-maps-attribution {
  color: var(--st-text-color);
  display: block;
  font-size: .75rem;
  line-height: 1.25;
  white-space: nowrap;
}
.tr-google-maps-attribution[hidden] { display: none; }
.tr-address button {
  align-self: flex-start;
  background: var(--st-secondary-background-color);
  border: 1px solid var(--st-widget-border-color, rgba(49, 51, 63, .2));
  border-radius: 6px;
  color: var(--st-text-color);
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  line-height: 1.25rem;
  min-height: 36px;
  padding: .375rem .75rem;
}
.tr-address button:hover { border-color: var(--st-primary-color); }
.tr-address button:focus-visible {
  border-color: var(--st-primary-color);
  box-shadow: 0 0 0 1px var(--st-primary-color);
  outline: none;
}
.tr-address button:disabled { cursor: wait; opacity: .65; }
.tr-address input {
  width: 100%;
  box-sizing: border-box;
  background: var(--st-secondary-background-color);
  border: 1px solid var(--st-widget-border-color, rgba(49, 51, 63, .2));
  border-radius: .375rem;
  color: var(--st-text-color);
  font: inherit;
  min-height: 2.5rem;
  padding: .5rem .75rem;
}
.tr-address input:focus {
  border-color: var(--st-primary-color);
  box-shadow: 0 0 0 1px var(--st-primary-color);
  outline: none;
}
#tr-address-host,
#tr-address-host > gmp-place-autocomplete {
  box-sizing: border-box;
  width: 100%;
}
#tr-address-host > gmp-place-autocomplete {
  background: var(--st-secondary-background-color);
  border: 0;
  border-radius: .375rem;
  height: 2.5rem;
  color-scheme: light;
  color: var(--st-text-color);
  display: block;
  font: inherit;
  min-height: 2.5rem;
  overflow: visible;
  padding: 0;
}
#tr-address-host > gmp-place-autocomplete::part(input),
#tr-address-host > gmp-place-autocomplete::part(prediction-list),
#tr-address-host > gmp-place-autocomplete::part(prediction-item) {
  background-color: var(--st-secondary-background-color);
  color: var(--st-text-color);
}
#tr-address-host > gmp-place-autocomplete::part(input) {
  background: var(--st-secondary-background-color);
  border: 1px solid var(--st-widget-border-color, rgba(49, 51, 63, .2));
  border-radius: 6px;
  box-shadow: none;
  box-sizing: border-box;
  color: var(--st-text-color);
  font: inherit;
  height: 2.5rem;
  line-height: 1.5rem;
  min-height: 2.5rem;
  padding: .5rem .75rem;
  width: 100%;
}
#tr-address-host > gmp-place-autocomplete::part(input):focus {
  border-color: var(--st-primary-color);
  box-shadow: 0 0 0 1px var(--st-primary-color);
  outline: none;
}
#tr-address-host > gmp-place-autocomplete::part(prediction-item-main-text),
#tr-address-host > gmp-place-autocomplete::part(prediction-item-secondary-text) {
  color: var(--st-text-color);
}
#tr-address-host > gmp-place-autocomplete::part(prediction-item-selected) {
  background-color: var(--st-background-color);
  color: var(--st-text-color);
}
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
  let providerFailed = data.providerFailed === true;
  let suppressInput = false;
  // Preserve the selected state when another address component causes a
  // Streamlit rerun and this component is initialized again.
  let selectedDisplay = data.placeId ? data.value || '' : '';

  function reportFailure(stage, error) {
    const message = error && error.message ? String(error.message) : '';
    const safeMessage = message.replace(
      /((?:api[_-]?key|key)=)[^&\\s]+/gi, '$1[redacted]'
    );
    console.error('[Tabula Rasa] Address autocomplete failed', {
      stage: stage,
      apiKeyConfigured: Boolean(data.apiKey),
      errorName: error && error.name ? String(error.name) : 'UnknownError',
      errorMessage: safeMessage.slice(0, 300)
    });
  }

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
  function showManual(message, initialValue) {
    hideAttribution();
    host.hidden = true;
    manual.hidden = false;
    manualButton.hidden = false;
    manualButton.textContent = 'Use Google suggestions';
    status.textContent = message || 'Google suggestions are unavailable.';
    const widget = host.querySelector('gmp-place-autocomplete');
    manualInput.value = initialValue ||
      (widget && widget.value) || data.value || '';
    manualInput.onchange = () => emit('manual', manualInput.value.trim());
    manualInput.focus();
  }
  function selectManualMode() {
    manualMode = true;
    providerFailed = false;
    console.info('[Tabula Rasa] Address autocomplete mode changed', {
      mode: 'manual'
    });
    setStateValue('manual_mode', true);
    setStateValue('failed', false);
    showManual('Use the recorded address field below.');
  }
  function selectGoogleMode() {
    manualMode = false;
    providerFailed = false;
    console.info('[Tabula Rasa] Address autocomplete mode changed', {
      mode: 'google',
      apiKeyConfigured: Boolean(data.apiKey)
    });
    setStateValue('manual_mode', false);
    setStateValue('failed', false);
    setup();
  }
  function loadMaps() {
    if (window.__tabulaRasaPlacesLibraryPromise) {
      return window.__tabulaRasaPlacesLibraryPromise;
    }
    if (!window.google) window.google = {};
    if (!window.google.maps) window.google.maps = {};
    const maps = window.google.maps;
    if (!maps.importLibrary) {
      const libraries = new Set();
      let bootstrapPromise;
      maps.__tabulaRasaBootstrapLoader = true;
      const loadBootstrap = () => {
        if (bootstrapPromise) return bootstrapPromise;
        bootstrapPromise = new Promise((resolve, reject) => {
          const script = document.createElement('script');
          const params = new URLSearchParams();
          params.set('key', data.apiKey);
          params.set('v', 'weekly');
          params.set('loading', 'async');
          params.set('libraries', [...libraries].join(','));
          params.set('callback', 'google.maps.__tabulaRasaMapsLoaded');
          script.src = 'https://maps.googleapis.com/maps/api/js?' + params;
          script.async = true;
          script.defer = true;
          script.dataset.tabulaRasaPlaces = 'true';
          maps.__tabulaRasaMapsLoaded = resolve;
          script.onerror = () => reject(
            new Error('Google Maps JavaScript API could not load')
          );
          document.head.appendChild(script);
        });
        return bootstrapPromise;
      };
      maps.importLibrary = (library, ...args) => {
        libraries.add(library);
        return loadBootstrap().then(() => maps.importLibrary(library, ...args));
      };
    }
    window.__tabulaRasaPlacesLibraryPromise = maps.importLibrary('places');
    return window.__tabulaRasaPlacesLibraryPromise;
  }
  function clearFailedMapsLoad() {
    const maps = window.google && window.google.maps;
    const customLoader = maps && maps.__tabulaRasaBootstrapLoader;
    const failedScript = document.querySelector('script[data-tabula-rasa-places]');
    if (failedScript) failedScript.remove();
    if (customLoader) {
      delete maps.importLibrary;
      delete maps.__tabulaRasaMapsLoaded;
      delete maps.__tabulaRasaBootstrapLoader;
    }
    window.__tabulaRasaPlacesPromise = null;
    window.__tabulaRasaPlacesLibraryPromise = null;
  }
  async function setup() {
    console.info('[Tabula Rasa] Address autocomplete setup', {
      manualMode: manualMode,
      apiKeyConfigured: Boolean(data.apiKey)
    });
    if (manualMode) { showManual('Use the recorded address field below.'); return; }
    if (!data.apiKey) { showManual('Use the recorded address field below.'); return; }
    manual.hidden = true;
    host.hidden = false;
    manualButton.hidden = true;
    status.textContent = 'Loading Google address suggestions…';
    try {
      const placesLibrary = await loadMaps();
      if (manualMode) {
        showManual('Use the recorded address field below.');
        return;
      }
      showAttribution();
      console.info('[Tabula Rasa] Google Maps JavaScript API loaded');
      const {PlaceAutocompleteElement} = placesLibrary || {};
      if (typeof PlaceAutocompleteElement !== 'function') {
        throw new Error('Places library has no autocomplete element');
      }
      const options = {
        includedPrimaryTypes: ['street_address', 'premise', 'establishment']
      };
      if (data.regionCode) options.includedRegionCodes = [data.regionCode];
      const element = new PlaceAutocompleteElement(options);
      element.setAttribute('aria-label', data.label || 'Address');
      element.value = data.value || '';
      element.style.width = '100%';
      element.style.boxSizing = 'border-box';
      element.style.fontFamily = 'inherit';
      host.replaceChildren(element);
      status.textContent = data.placeId ?
        'Address selected.' :
        'Start typing to choose a Google-verified address.';
      // PlaceAutocompleteElement owns the Google session lifecycle. Do not
      // create a parallel token here (that can result in duplicate billing).
      element.addEventListener('change', () => {
        // PlaceAutocompleteElement can dispatch a generic change immediately
        // after gmp-select. Do not let that follow-up event erase the Place ID
        // that the selected event just produced.
        if (suppressInput || (selectedDisplay && element.value === selectedDisplay)) {
          return;
        }
        selectedDisplay = '';
        version += 1;
        setTriggerValue('changed', {
          display_text: element.value || '', place_id: '', version: version
        });
      });
      element.addEventListener('gmp-select', async (event) => {
        suppressInput = true;
        status.textContent = 'Loading selected address…';
        try {
          const prediction = event.placePrediction;
          const place = prediction && prediction.toPlace ?
            prediction.toPlace() : null;
          if (!place) throw new Error('No place returned');
          // The Place ID is needed only for the current routing request. Do
          // not fetch or return provider-formatted address content: the
          // durable ledger text is collected separately by the Mileage UI.
          await place.fetchFields({fields: ['id']});
          const display = element.value || '';
          selectedDisplay = display;
          version += 1;
          setTriggerValue('selected', {
            display_text: display, place_id: place.id || '', version: version
          });
          status.textContent = 'Address selected.';
        } catch (error) {
          // Keep the browser error useful without exposing API details.
          reportFailure('Google place selection', error);
          status.textContent = 'The address could not be selected. Use the recorded address field below.';
          selectedDisplay = '';
          version += 1;
          setTriggerValue('changed', {
            display_text: element.value || '', place_id: '', version: version
          });
        } finally {
          suppressInput = false;
        }
      });
      element.addEventListener('gmp-error', () => {
        reportFailure('Google Places provider event', null);
        status.textContent = 'Google address suggestions are unavailable.';
        manualMode = true;
        providerFailed = true;
        setStateValue('manual_mode', true);
        setStateValue('failed', true);
        selectedDisplay = '';
        emit('changed', element.value || '');
        showManual('Google address suggestions are unavailable.');
        manualButton.hidden = false;
      });
      manualButton.onclick = () => {
        if (manual.hidden) selectManualMode();
        else selectGoogleMode();
      };
    } catch (error) {
      reportFailure('Google Maps JavaScript API load or setup', error);
      clearFailedMapsLoad();
      selectedDisplay = '';
      const widget = host.querySelector('gmp-place-autocomplete');
      emit('changed', (widget && widget.value) || '');
      showManual('Google address suggestions are unavailable.');
      manualMode = true;
      providerFailed = true;
      setStateValue('manual_mode', true);
      setStateValue('failed', true);
      manualButton.onclick = selectGoogleMode;
    }
  }
  // The Mileage page exposes its recorded-text field as the direct manual
  // entry path. Keep this recovery control hidden during normal operation;
  // it is shown only after a provider failure so Google can be retried.
  manualButton.hidden = true;
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

# Components-v2 validates every key in ``default`` against the states declared
# by the corresponding ``on_<state>_change`` callback. Keep this contract
# explicit because provider failure and user-selected manual mode are distinct
# pieces of state.
_COMPONENT_STATE_NAMES = frozenset(
    {"selected", "manual", "changed", "failed", "manual_mode"}
)


def _component_default_state(
    *, manual_mode: bool, failed: bool
) -> dict[str, bool]:
    """Return defaults using only declared components-v2 state names."""
    defaults = {"manual_mode": manual_mode, "failed": failed}
    undeclared = set(defaults) - _COMPONENT_STATE_NAMES
    if undeclared:
        names = ", ".join(sorted(undeclared))
        raise RuntimeError(f"Undeclared address component state: {names}")
    return defaults


def browser_api_key_from_secrets(
    secrets_mapping: Mapping[str, Any],
) -> str | None:
    """Return the browser key only when it is distinct from the Routes key.

    A mistakenly reused server key must fail closed instead of crossing the
    Streamlit component boundary. The Routes client can remain available, but
    autocomplete falls back to manual entry until two separate keys are set.
    """
    if not isinstance(secrets_mapping, Mapping):
        return None
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
            "placeId": current.place_id,
            "regionCode": _region_code(region_code),
            "manualMode": manual_mode,
            "providerFailed": bool(component_state.get("failed", False))
            if isinstance(component_state, Mapping)
            else False,
        },
        default=_component_default_state(manual_mode=manual_mode, failed=False),
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
