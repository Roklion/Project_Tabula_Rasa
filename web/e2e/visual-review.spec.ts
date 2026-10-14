import { expect, test } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { visualReview } from '../visual-review.ts';

let server: ViteDevServer;
let origin: string;
test.beforeAll(async () => {
  server = await createServer({ configFile: false, plugins: [visualReview()],
    server: { host: '127.0.0.1', port: 0,
      // Even an accidentally retained proxy cannot receive a preview request.
      proxy: { '/api': { target: 'http://127.0.0.1:1' } } },
  });
  await server.listen();
  origin = server.resolvedUrls!.local[0];
});
test.afterAll(async () => { await server?.close(); });

test('manual preview serves the shared synthetic financial, form and receipt fixtures', async () => {
  const read = async (path: string) => (await fetch(new URL(path, origin))).json();
  expect(await read('/api/v1/session')).toMatchObject({ actor_id: 'synthetic', entity: { id: 'alpha' } });
  expect(await read('/api/v1/entities/alpha/reports/summary')).toMatchObject({ profit_loss: { net: '-150.25' } });
  expect(await read('/api/v1/entities/alpha/ledger')).toMatchObject({ items: [{ record_id: 'ordinary' }, {}, {}] });
  expect(await read('/api/v1/entities/alpha/accounts')).toMatchObject({ items: [{ id: 'account' }, {}] });
  expect(await read('/api/v1/entities/alpha/transactions/transaction/receipts')).toMatchObject({ items: [{ mime_type: 'application/pdf' }] });
});

test('preview rejects writes and auth/provider/content routes without a proxy fallthrough', async () => {
  for (const [method, path] of [
    ['POST', '/api/v1/entities/alpha/transactions'], ['PATCH', '/api/v1/entities/alpha/accounts/account'],
    ['DELETE', '/api/v1/entities/alpha/transactions/transaction/receipts/document'],
    ['GET', '/api'], ['GET', '/api/v2/session'],
  ]) {
    const response = await fetch(new URL(path, origin), { method });
    expect(response.status).toBe(405);
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(await response.json()).toMatchObject({ request_id: 'synthetic-preview-read-only' });
  }
  for (const path of ['/api/v1/auth/login', '/api/v1/entities/alpha/documents/document/content']) {
    const response = await fetch(new URL(path, origin));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ items: [] });
  }
});
