import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('accountant handoff scope, safe failure and explicit retry are accessible', async ({ page }) => {
  const session = { state: 'ready', actor_id: 'synthetic-owner', organization_id: 'synthetic-org',
    entity: { id: 'alpha', name: 'Alpha demonstration' }, capabilities: ['bookkeeping:read', 'bookkeeping:export'],
    cache_scope: 'handoff-alpha', csrf_token: 'synthetic-csrf', trusted_development: false };
  await page.route('**/api/v1/session', route => route.fulfill({ json: session }));
  await page.route('**/api/v1/businesses', route => route.fulfill({ json: { items: [session.entity] } }));
  await page.route('**/api/v1/auth/activity', route => route.fulfill({ status: 204 }));
  let attempts = 0;
  await page.route('**/api/v1/entities/alpha/exports/handoff', async route => {
    attempts += 1;
    expect(route.request().method()).toBe('POST');
    expect(route.request().headers()['x-csrf-token']).toBe('synthetic-csrf');
    expect(route.request().postDataJSON()).toEqual({ scope: attempts === 1 ? 'documents_inclusive' : 'metadata_only' });
    await route.fulfill(attempts === 1
      ? { status: 503, json: { error: { code: 'unavailable', message: 'Unavailable', fields: [] }, request_id: 'synthetic' } }
      : { contentType: 'application/zip', body: Buffer.from('synthetic transport fixture') });
  });
  await page.goto('/data');
  const panel = page.getByRole('region', { name: 'Accountant handoff' });
  await expect(panel.getByRole('combobox', { name: 'Archive scope' })).toHaveValue('documents_inclusive');
  await expect(panel).toContainText('Audit history, credentials and operational policies are excluded');
  await panel.getByRole('button', { name: 'Download handoff ZIP' }).click();
  await expect(panel.getByRole('alert')).toBeVisible();
  await expect(panel).toContainText('No partial archive was delivered');
  expect(attempts).toBe(1);
  await panel.getByRole('combobox', { name: 'Archive scope' }).selectOption('metadata_only');
  await expect(panel).toContainText('Receipt files are excluded');
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('customer-handoff.png'), fullPage: true });
  const download = page.waitForEvent('download');
  await panel.getByRole('button', { name: 'Download handoff ZIP' }).click();
  expect((await download).suggestedFilename()).toBe('tabula-rasa-handoff.zip');
  expect(attempts).toBe(2);
});
