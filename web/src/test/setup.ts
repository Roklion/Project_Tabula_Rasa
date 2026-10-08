import '@testing-library/jest-dom/vitest';
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
