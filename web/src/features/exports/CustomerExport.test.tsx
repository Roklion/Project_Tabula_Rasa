import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../../api/client';
import { EntityContext } from '../../app/context';
import { session } from '../../test/fixtures';
import * as downloads from '../../components/downloadBlob';
import { CustomerExport } from './CustomerExport';

afterEach(() => vi.restoreAllMocks());

it('discloses exclusions and denies full handoff to ordinary readers', () => {
  render(<EntityContext value={session}><CustomerExport /></EntityContext>);
  expect(screen.getByText(/Audit history, credentials and operational policies are excluded/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Download handoff ZIP' })).not.toBeInTheDocument();
  expect(screen.getByText(/Full export requires/)).toBeInTheDocument();
});

it('uses explicit scope, shows progress and aborts late private delivery on unmount', async () => {
  let complete: (blob: Blob) => void = () => undefined;
  const download = vi.spyOn(api, 'downloadCustomerExport').mockReturnValue(new Promise(resolve => { complete = resolve; }));
  const save = vi.spyOn(downloads, 'downloadBlob').mockImplementation(() => undefined);
  const owner = { ...session, capabilities: [...session.capabilities, 'bookkeeping:export'] };
  const view = render(<EntityContext value={owner}><CustomerExport /></EntityContext>);
  fireEvent.change(screen.getByRole('combobox', { name: 'Archive scope' }), { target: { value: 'metadata_only' } });
  expect(screen.getByText(/Receipt files are excluded/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Download handoff ZIP' }));
  expect(screen.getByText('Preparing and checking archive…')).toBeInTheDocument();
  expect(download.mock.calls[0][1]).toBe('metadata_only');
  const signal = download.mock.calls[0][2]!;
  view.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => { complete(new Blob(['private'])); });
  expect(save).not.toHaveBeenCalled();
});
