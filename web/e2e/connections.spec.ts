import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/auth/activity', route => route.fulfill({ status: 204 }));
});

test('owner connection confirmation is accessible and usable at desktop and mobile widths', async ({ page }) => {
  const session = { state: 'ready', actor_id: 'synthetic-owner', organization_id: 'synthetic-org',
    entity: { id: 'alpha', name: 'Alpha demonstration' }, capabilities: ['bookkeeping:read', 'connections:manage'],
    cache_scope: 'connections-alpha', csrf_token: 'synthetic-csrf', trusted_development: false };
  let revision = 1;
  let status = 'pending';
  await page.route('**/api/v1/session', route => route.fulfill({ json: session }));
  await page.route('**/api/v1/businesses', route => route.fulfill({ json: { items: [session.entity] } }));
  await page.route('**/api/v1/entities/alpha/connections/google-drive', async route => {
    if (route.request().method() === 'POST') {
      expect(route.request().postDataJSON()).toEqual({ revision, connect: status !== 'connected' });
      expect(route.request().headers()['x-csrf-token']).toBe('synthetic-csrf');
      status = status === 'connected' ? 'disconnected' : 'connected';
      revision += 1;
    }
    await route.fulfill({ json: { provider: 'google_drive', status, revision } });
  });
  for (const width of [1440, 390]) {
    status = 'pending'; revision = 1;
    await page.setViewportSize({ width, height: width < 760 ? 844 : 1000 });
    await page.goto('/data');
    const panel = page.getByRole('region', { name: 'External connections' });
    await expect(panel.getByText('Ready for owner connection')).toBeVisible();
    await panel.getByRole('button', { name: 'Connect Google Drive' }).click();
    const dialog = page.getByRole('alertdialog', { name: 'Connect Google Drive' });
    await expect(dialog).toBeVisible();
    expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([]);
    await page.screenshot({ path: test.info().outputPath('connect-' + width + '.png'), fullPage: true });
    await dialog.getByRole('button', { name: 'Connect Google Drive' }).click();
    await expect(panel.getByText('Google Drive is connected for this business.')).toBeVisible();
    await panel.getByRole('button', { name: 'Disconnect Google Drive' }).click();
    await expect(page.getByRole('alertdialog')).toContainText('does not revoke Google consent');
    await page.getByRole('alertdialog').getByRole('button', { name: 'Disconnect Google Drive' }).click();
    await expect(panel.getByText('Google Drive is disconnected for this business.')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
});

test('ordinary commercial members have no legacy or connection administration controls', async ({ page }) => {
  await page.route('**/api/v1/session', route => route.fulfill({ json: {
    state: 'ready', actor_id: 'synthetic-reader', organization_id: 'synthetic-org',
    entity: { id: 'alpha', name: 'Alpha demonstration' }, capabilities: ['bookkeeping:read'],
    cache_scope: 'reader-alpha', csrf_token: 'synthetic-csrf', trusted_development: false,
  } }));
  await page.route('**/api/v1/businesses', route => route.fulfill({ json: { items: [{ id: 'alpha', name: 'Alpha demonstration' }] } }));
  await page.goto('/data');
  await expect(page.getByRole('heading', { name: 'Data & backup', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'External connections' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Account settings', exact: true })).toHaveCount(0);
});
