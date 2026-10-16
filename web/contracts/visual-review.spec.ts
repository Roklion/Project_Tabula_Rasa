import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, rm, rename, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { sourceHash, sourceStatus } from '../e2e/visual-evidence';
import { expect, test } from '@playwright/test';
import { type ViteDevServer } from 'vite';
import { startVisualPreview } from '../e2e/visual-preview-server';

let server: ViteDevServer;
let origin: string;
test.beforeAll(async () => { ({ server, origin } = await startVisualPreview()); });
test.afterAll(async () => { await server?.close(); });

test('manual preview serves the shared synthetic financial, form and receipt fixtures', async () => {
  const read = async (path: string) => (await fetch(new URL(path, origin))).json();
  expect(await read('/api/v1/session')).toMatchObject({ actor_id: 'synthetic', entity: { id: 'alpha' } });
  expect(await read('/api/v1/entities/alpha/reports/summary')).toMatchObject({ profit_loss: { net: '-150.25' } });
  expect(await read('/api/v1/entities/alpha/ledger')).toMatchObject({ items: [{ record_id: 'ordinary' }, {}, {}] });
  expect(await read('/api/v1/entities/alpha/journals')).toMatchObject({ items: [{ id: 'entry', postings: [{ side: 'Debit' }, { side: 'Credit' }] }] });
  expect(await read('/api/v1/entities/alpha/accounts')).toMatchObject({ items: [{ id: 'account' }, { id: 'accumulated' }, { id: 'equity' }] });
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
    ['GET', '/api/v1/entities/alpha/mixed-use/allocation'],
    ['GET', '/api/v1/entities/alpha/mixed-use/mixed/copy-draft'],
    ['GET', '/api/v1/entities/alpha/mileage/routes'],
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
    await writeFile(join(root, 'web/tsconfig.json'), JSON.stringify({ compilerOptions: { jsx: 'react-jsx' } }));
    const compilerChanged = await sourceHash(root);
    expect(compilerChanged).not.toBe(assetChanged);
    await writeFile(join(root, '.env'), 'SYNTHETIC_CONFIG=excluded');
    expect(await sourceHash(root)).toBe(compilerChanged);
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


test('evidence status retains public changes without exposing unrelated file metadata', async () => {
  const root = await mkdtemp(join(tmpdir(), 'tabula-status-evidence-'));
  try {
    execFileSync('git', ['init', '--quiet', root]);
    await mkdir(join(root, 'web/src'), { recursive: true });
    await writeFile(join(root, 'web/src/public.ts'), 'export const synthetic = true;');
    execFileSync('git', ['-C', root, 'add', 'web']);
    await writeFile(join(root, 'web/src/public.ts'), 'export const synthetic = false;');
    await writeFile(join(root, 'web/src/new-public.ts'), 'export const other = true;');
    const expected = sourceStatus(root);
    expect(expected).toContain('web/src/public.ts');
    expect(expected).toContain('web/src/new-public.ts');
    for (const filename of ['synthetic-receipt.pdf', 'synthetic-import.xlsx', 'synthetic-backup.zip']) {
      await writeFile(join(root, filename), 'synthetic unrelated bytes');
    }
    expect(sourceStatus(root)).toBe(expected);
    expect(sourceStatus(root)).not.toMatch(/receipt|import|backup/);
  } finally { await rm(root, { recursive: true, force: true }); }
});
