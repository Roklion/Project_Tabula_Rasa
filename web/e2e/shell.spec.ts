import { expect, test } from '@playwright/test';

const session = {
  actor_id: 'synthetic', organization_id: 'synthetic', entity: { id: 'alpha', name: 'Alpha demonstration' },
  capabilities: ['bookkeeping:read', 'bookkeeping:write'], cache_scope: 'e2e-alpha', csrf_token: 'synthetic-csrf',
  trusted_development: true,
};

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/session', route => route.fulfill({ json: session }));
  await page.route('**/api/v1/entities/alpha/accounts?*', route => route.fulfill({ json: { items: [] } }));
});

test('deep links, navigation, responsive layout and empty state', async ({ page }) => {
  for (const width of [1440, 1200, 900, 390, 320]) {
    await page.setViewportSize({ width, height: width < 760 ? 844 : 1000 });
    await page.goto('/accounts');
    await expect(page.getByRole('heading', { name: 'Accounts', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'No accounts yet' })).toBeVisible();
    if (width <= 760) await page.getByRole('button', { name: 'Menu', exact: true }).click();
    await page.getByRole('link', { name: 'Reports', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Reports', exact: true })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath('shell-' + width + '.png'), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
});

test('visible validation, conflict and unavailable states with request references', async ({ page }) => {
  for (const code of ['validation', 'stale', 'unavailable']) {
    await page.route('**/api/v1/entities/alpha/accounts?*', route => route.fulfill({
      status: code === 'stale' ? 409 : code === 'validation' ? 422 : 503,
      json: { error: { code, message: 'Safe transport message' }, request_id: 'smoke-reference' },
    }));
    await page.goto('/accounts');
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.getByText('Request reference: smoke-reference')).toBeVisible();
    await expect(page.getByRole('button', { name: code === 'stale' ? 'Review latest record' : 'Reload' })).toBeVisible();
  }
});

test('unknown route and unavailable context are safe', async ({ page }) => {
  await page.goto('/missing');
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
  await page.route('**/api/v1/session', route => route.fulfill({
    status: 401, json: { error: { code: 'unauthorized', message: 'Sign in' }, request_id: 'context-ref' },
  }));
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Business access is unavailable');
  await expect(page.getByRole('navigation')).toHaveCount(0);
});
