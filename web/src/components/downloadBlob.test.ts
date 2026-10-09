import { expect, it, vi } from 'vitest';
import { downloadBlob } from './downloadBlob';

it('retains the URL while initiating download and releases it afterwards', () => {
  vi.useFakeTimers();
  const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test-download');
  const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.isConnected).toBe(true);
    expect(this.download).toBe('receipt.pdf');
    expect(revoke).not.toHaveBeenCalled();
  });
  try {
    downloadBlob(new Blob(['synthetic']), 'receipt.pdf');
    expect(create).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(document.querySelector('a[download]')).toBeNull();
    expect(revoke).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(revoke).toHaveBeenCalledWith('blob:test-download');
  } finally { vi.useRealTimers(); vi.restoreAllMocks(); }
});
