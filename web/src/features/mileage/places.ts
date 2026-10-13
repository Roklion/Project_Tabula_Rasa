// Places owns its prediction session. Only the restricted browser key reaches
// this loader; Routes and human OAuth credentials stay behind the HTTP boundary.
export type PlaceWidget = HTMLElement & { value: string };
type Place = { id?: string; fetchFields: (options: { fields: string[] }) => Promise<unknown> };
export type PlaceSelectEvent = Event & { placePrediction: { toPlace: () => Place } };
type Library = { PlaceAutocompleteElement: new (options: { includedPrimaryTypes: string[]; includedRegionCodes?: string[] }) => PlaceWidget };
type MapsWindow = Window & { google?: { maps: { importLibrary: (name: string) => Promise<Library> } }; tabulaPlacesReady?: () => void };
let loading: Promise<Library> | undefined;

export function loadPlaces(browserKey: string): Promise<Library> {
  if (loading) return loading;
  const provider = window as MapsWindow;
  if (provider.google?.maps.importLibrary) return provider.google.maps.importLibrary('places');
  loading = new Promise<Library>((resolve, reject) => {
    const script = document.createElement('script');
    const timer = window.setTimeout(fail, 15000);
    function fail() {
      window.clearTimeout(timer); script.remove(); delete provider.tabulaPlacesReady;
      loading = undefined; reject(new Error('Address suggestions are unavailable.'));
    }
    provider.tabulaPlacesReady = () => {
      window.clearTimeout(timer); delete provider.tabulaPlacesReady;
      const imported = provider.google?.maps.importLibrary('places');
      if (!imported) { fail(); return; }
      void imported.then(resolve).catch(fail);
    };
    script.src = 'https://maps.googleapis.com/maps/api/js?' + new URLSearchParams({
      key: browserKey, v: 'weekly', loading: 'async', libraries: 'places', callback: 'tabulaPlacesReady',
    });
    script.async = true; script.onerror = fail;
    document.head.appendChild(script);
  });
  return loading;
}
