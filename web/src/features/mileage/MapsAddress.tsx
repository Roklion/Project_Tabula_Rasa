import { useEffect, useRef, useState } from 'react';
import { loadPlaces, type PlaceSelectEvent } from './places';

export type SelectedPlace = { placeId: string; text: string };

export function MapsAddress({ browserKey, regionCode, label, onSelect, onClear }: {
  browserKey: string; regionCode: string | null; label: string;
  onSelect: (place: SelectedPlace) => void; onClear: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState('Loading Google address suggestions…');
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    let generation = 0;
    let cleanup: (() => void) | undefined;
    const fail = () => {
      if (!active) return;
      generation += 1; onClear(); setFailed(true);
      setStatus('Google address suggestions are unavailable. Enter the recorded location manually.');
      host.current?.replaceChildren();
    };
    void loadPlaces(browserKey).then(({ PlaceAutocompleteElement }) => {
      if (!active) return;
      const element = new PlaceAutocompleteElement({ includedPrimaryTypes: ['street_address', 'premise', 'establishment'],
        ...(regionCode ? { includedRegionCodes: [regionCode] } : {}) });
      element.setAttribute('aria-label', label);
      let selectedText = '';
      let selecting = false;
      function changed() {
        if (selecting || (selectedText && selectedText === element.value)) return;
        generation += 1; selectedText = ''; onClear();
        setStatus('Choose a Google suggestion to calculate mileage.');
      }
      async function selected(event: Event) {
        const current = ++generation;
        selecting = true; onClear(); setStatus('Loading selected address…');
        try {
          const place = (event as PlaceSelectEvent).placePrediction.toPlace();
          await place.fetchFields({ fields: ['id'] });
          if (!active || generation !== current) return;
          if (!place.id) { fail(); return; }
          selectedText = element.value;
          onSelect({ placeId: place.id, text: selectedText }); setStatus('Address selected. Review the recorded location below.');
        } catch { if (active && generation === current) fail(); }
        finally { if (generation === current) selecting = false; }
      }
      element.addEventListener('change', changed); element.addEventListener('input', changed);
      element.addEventListener('gmp-select', selected); element.addEventListener('gmp-error', fail);
      host.current?.replaceChildren(element);
      setStatus('Choose a Google suggestion to calculate mileage.'); setFailed(false);
      cleanup = () => { element.removeEventListener('change', changed); element.removeEventListener('input', changed);
        element.removeEventListener('gmp-select', selected); element.removeEventListener('gmp-error', fail); element.remove(); };
    }).catch(fail);
    return () => { active = false; generation += 1; cleanup?.(); };
  }, [browserKey, regionCode, label, onSelect, onClear, attempt]);
  return <div className="field mapsLookup"><p>{label}</p><div ref={host} />
    <small role="status">{status}</small>
    {failed && <button type="button" onClick={() => { setStatus('Loading Google address suggestions…'); setAttempt(value => value + 1); }}>Retry Google suggestions</button>}
  </div>;
}
