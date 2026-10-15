import { expect, test } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, rm, rename, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { sourceHash } from './visual-evidence';

let server: ViteDevServer;
let origin: string;
test.beforeAll(async () => {
  server = await createServer({ configFile: resolve('vite.visual-review.config.ts'),
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
    ['GET', '/api'], ['GET', '/api/v2/session'], ['GET', '/api/v1/auth/login'],
    ['GET', '/api/v1/entities/alpha/documents/document/content'],
    ['GET', '/api/v1/entities/alpha/exports/transactions.csv'],
    ['GET', '/api/v1/entities/alpha/unknown'],
  ]) {
    const response = await fetch(new URL(path, origin), { method });
    expect(response.status).toBe(405);
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(await response.json()).toMatchObject({ request_id: 'synthetic-preview-read-only' });
  }
});


test('evidence digest binds HTML and public rendering assets while excluding private configuration', async () => {
  const root = await mkdtemp(join(tmpdir(), 'tabula-public-evidence-'));
  try {
    execFileSync('git', ['init', '--quiet', root]);
    await mkdir(join(root, 'web/public'), { recursive: true });
    await writeFile(join(root, 'web/index.html'), '<html>synthetic first entry</html>');
    await writeFile(join(root, 'web/public/mark.svg'), '<svg>synthetic first asset</svg>');
    const first = await sourceHash(root);
    await writeFile(join(root, 'web/index.html'), '<html>synthetic second entry</html>');
    const htmlChanged = await sourceHash(root);
    expect(htmlChanged).not.toBe(first);
    await writeFile(join(root, 'web/public/mark.svg'), '<svg>synthetic second asset</svg>');
    const assetChanged = await sourceHash(root);
    expect(assetChanged).not.toBe(htmlChanged);
    await writeFile(join(root, '.env'), 'SYNTHETIC_CONFIG=excluded');
    expect(await sourceHash(root)).toBe(assetChanged);
  } finally { await rm(root, { recursive: true, force: true }); }
});


test('dirty tracked deletion and rename retain distinct reproducible source digests', async () => {
  const root = await mkdtemp(join(tmpdir(), 'tabula-deleted-evidence-'));
  try {
    execFileSync('git', ['init', '--quiet', root]);
    await mkdir(join(root, 'web/public'), { recursive: true });
    const asset = join(root, 'web/public/mark.svg');
    await writeFile(join(root, 'web/index.html'), '<html>synthetic</html>');
    await writeFile(asset, '<svg>synthetic</svg>');
    execFileSync('git', ['-C', root, 'add', 'web']);
    const present = await sourceHash(root);
    await rm(asset);
    const absent = await sourceHash(root);
    expect(absent).not.toBe(present);
    expect(await sourceHash(root)).toBe(absent);
    await writeFile(asset, '');
    expect(await sourceHash(root)).not.toBe(absent);
    await rename(join(root, 'web/index.html'), join(root, 'web/renamed.html'));
    expect(await sourceHash(root)).not.toBe(present);
  } finally { await rm(root, { recursive: true, force: true }); }
});
