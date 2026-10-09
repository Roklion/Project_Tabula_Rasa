import '@testing-library/jest-dom/vitest';

// jsdom has no top layer. Native browser tests verify inertness, focus trapping,
// Escape and restoration; this shim only lets component tests render dialogs.
HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// jsdom has no browser Request implementation; emulate browser-relative URLs.
const NativeRequest = globalThis.Request;
class BrowserRequest extends NativeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(typeof input === 'string' ? new URL(input, 'http://127.0.0.1') : input, init);
  }
}
globalThis.Request = BrowserRequest;
afterEach(cleanup);
