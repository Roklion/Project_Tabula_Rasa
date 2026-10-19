import { expect, test } from '@playwright/test';
import { startVisualPreview } from './visual-preview-server';

let close: (() => Promise<void>) | undefined;
let origin: string;
test.beforeAll(async () => { ({ close, origin } = await startVisualPreview()); });
test.afterAll(async () => { await close?.(); });

test('explicit preview renders journals and opens the same journal from the ledger', async ({ page }) => {
  await page.goto(new URL('/journals', origin).href);
  await expect(page.getByRole('region', { name: 'Journals', exact: true })).toContainText('Complete synthetic journal');
  await page.getByRole('button', { name: 'Edit 2026-10-06 · Complete synthetic journal', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Edit journal', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Posting 2', exact: true })).toBeVisible();
  await page.goto(new URL('/transactions', origin).href);
  await page.getByRole('button', { name: 'Edit 2026-10-06 · Complete synthetic journal · 40.00', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Edit journal', exact: true })).toBeVisible();
  await expect(page.getByRole('status')).toContainText('Difference: 0.00');
});


test('preview admits only exact non-mutating mixed-use POST preparation routes', async ({ page }) => {
  for (const path of ['/api/v1/entities/alpha/mixed-use/allocation', '/api/v1/entities/alpha/mixed-use/mixed/copy-draft']) {
    const response = await fetch(new URL(path, origin), { method: 'POST', body: '{}' });
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject(path.endsWith('allocation') ? { allocated_amount: '740.74' } : { source_id: 'synthetic-copy-source' });
  }
  for (const path of ['/api/v1/entities/alpha/mixed-use', '/api/v1/entities/alpha/mixed-use/mixed', '/api/v1/entities/alpha/mixed-use/mixed/copy']) {
    expect((await fetch(new URL(path, origin), { method: 'POST', body: '{}' })).status).toBe(405);
  }
  await page.goto(new URL('/mixed-use/mixed/copy', origin).href);
  await expect(page.getByRole('heading', { name: 'Copy mixed-use expense', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save mixed-use copy', exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.goto(new URL('/mixed-use/mixed', origin).href);
  await expect(page.getByRole('heading', { name: 'Edit mixed-use expense', exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});
