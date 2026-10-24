import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { coreResponse } from './core-fixture';

test('sidebar usage is keyboard accessible, lazy and compact at desktop and mobile widths', async ({ page }) => {
  let statusRequests = 0;
  const loads: boolean[] = [];
  await page.route('**/api/v1/**', async route => {
    if (new URL(route.request().url()).pathname.endsWith('/maps/usage')) {
      if (route.request().method() === 'GET') {
        statusRequests += 1;
        await route.fulfill({ json: { status: 'not_loaded', services: [], cache_remaining_seconds: 0 } });
      } else {
        loads.push(route.request().postDataJSON().refresh);
        expect(route.request().headers()['x-csrf-token']).toBe('synthetic');
        await route.fulfill({ json: { status: 'ready', cache_remaining_seconds: 120, services: [
          { title: 'Routes API', rows: ['ComputeRoutes: 120/Unlimited (per minute)'] },
          { title: 'Places API (New)', rows: ['Autocomplete requests: 0/60 (per minute)'] },
        ] } });
      }
    } else await route.fulfill({ json: coreResponse(new URL(route.request().url())) });
  });
  await page.goto('/accounts');
  await expect(page.getByRole('heading', { name: 'Accounts', exact: true })).toBeVisible();
  expect(statusRequests).toBe(0); expect(loads).toEqual([]);
  const summary = page.locator('summary').filter({ hasText: 'Google Maps API usage' });
  await summary.focus(); await summary.press('Enter');
  await expect(page.getByRole('button', { name: 'Load usage' })).toBeEnabled();
  expect(statusRequests).toBe(1); expect(loads).toEqual([]);
  await page.getByRole('button', { name: 'Load usage' }).click();
  await expect(page.getByRole('region', { name: 'Routes API' })).toContainText('ComputeRoutes: 120/Unlimited (per minute)');
  await expect(page.getByRole('region', { name: 'Places API (New)' })).toContainText('Autocomplete requests: 0/60 (per minute)');
  await expect(page.getByText(/15-minute lookback/)).toContainText('240 seconds');
  await page.getByRole('button', { name: 'Refresh' }).click();
  await expect(page.getByRole('button', { name: 'Refresh' })).toBeEnabled();
  expect(loads).toEqual([false, true]);
  const accessibility = await new AxeBuilder({ page }).include('aside').withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
  expect(accessibility.violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('maps-usage.png'), fullPage: true });
  await summary.click();
  await expect(page.getByRole('button', { name: 'Refresh' })).toBeHidden();
  expect(loads).toEqual([false, true]);
});
