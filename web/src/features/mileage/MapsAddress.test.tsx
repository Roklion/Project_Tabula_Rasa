import { act, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { MapsAddress } from './MapsAddress';
import { loadPlaces } from './places';

vi.mock('./places', () => ({ loadPlaces: vi.fn() }));

class TestPlaceWidget extends HTMLElement { value = ''; }
customElements.define('test-address-request-widget', TestPlaceWidget);

function request() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((done, fail) => { resolve = done; reject = fail; });
  return { resolve, reject, fetchFields: () => promise };
}

async function lookup() {
  vi.mocked(loadPlaces).mockResolvedValue({ PlaceAutocompleteElement: TestPlaceWidget });
  const onSelect = vi.fn();
  render(<MapsAddress browserKey="synthetic" regionCode={null} label="Address lookup"
    onSelect={onSelect} onClear={vi.fn()} />);
  const widget = await screen.findByLabelText('Address lookup') as TestPlaceWidget;
  function select(id: string, pending: ReturnType<typeof request>) {
    widget.value = id;
    widget.dispatchEvent(Object.assign(new Event('gmp-select'), {
      placePrediction: { toPlace: () => ({ id, fetchFields: pending.fetchFields }) },
    }));
  }
  return { widget, select, onSelect };
}

it.each(['success', 'failure'])('keeps the newer address lookup when a superseded request ends in %s', async outcome => {
  const { widget, select, onSelect } = await lookup();
  const older = request(); const newer = request();
  act(() => { select('old', older); select('new', newer); });
  await act(async () => { if (outcome === 'failure') older.reject(new Error('unavailable')); else older.resolve(); });
  expect(widget).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Loading selected address');
  expect(onSelect).not.toHaveBeenCalled();
  await act(async () => newer.resolve());
  expect(onSelect).toHaveBeenCalledWith({ placeId: 'new', text: 'new' });
  expect(screen.getByRole('status')).toHaveTextContent('Address selected');
  expect(screen.queryByRole('button', { name: 'Retry Google suggestions' })).not.toBeInTheDocument();
});

it('retains manual-entry guidance and explicit retry when the current address request fails', async () => {
  const { widget, select, onSelect } = await lookup();
  const current = request();
  act(() => select('current', current));
  await act(async () => current.reject(new Error('unavailable')));
  expect(widget).not.toBeInTheDocument();
  expect(onSelect).not.toHaveBeenCalled();
  expect(screen.getByRole('status')).toHaveTextContent('Enter the recorded location manually');
  expect(screen.getByRole('button', { name: 'Retry Google suggestions' })).toBeVisible();
});
