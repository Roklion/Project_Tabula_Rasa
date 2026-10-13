import { act, fireEvent, render, screen } from '@testing-library/react';
import { RouterProvider } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../../api/client';
import { createTestRouter } from '../../app/router';
import { session } from '../../test/fixtures';
import * as downloads from '../../components/downloadBlob';

afterEach(() => vi.restoreAllMocks());

it('cancels receipt transport and never downloads a late private result after scope unmount', async () => {
  vi.spyOn(api, 'session').mockResolvedValue(session);
  vi.spyOn(api, 'entities').mockResolvedValue({ items: [session.entity] });
  vi.spyOn(api, 'transactionDocuments').mockResolvedValue({ items: [
    { id: 'doc', filename: 'synthetic.pdf', mime_type: 'application/pdf', byte_size: 1, sha256: 'a'.repeat(64) },
  ], needing_integrity: 0 });
  vi.spyOn(api, 'unreferencedDocuments').mockResolvedValue({ items: [], needing_integrity: 0 });
  vi.spyOn(api, 'transactions').mockResolvedValue({ items: [] });
  let complete: (value: Blob) => void = () => undefined;
  const download = vi.spyOn(api, 'downloadDocument').mockReturnValue(new Promise(resolve => { complete = resolve; }));
  const save = vi.spyOn(downloads, 'downloadBlob').mockImplementation(() => undefined);
  const view = render(<RouterProvider router={createTestRouter(['/transactions/txn/receipts'])} />);
  fireEvent.click(await screen.findByRole('link', { name: 'Download synthetic.pdf' }));
  const signal = download.mock.calls[0][2]!;
  expect(signal.aborted).toBe(false);
  view.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => { complete(new Blob(['synthetic private result'])); });
  expect(save).not.toHaveBeenCalled();
});
