import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { coreResponse, ordinary, owned, journal } from './core-fixture';
import { captureEvidence, retainEvidence } from './visual-evidence';

test.afterEach(async () => { await retainEvidence(test.info()); });

test('recurring Type badges preserve accounting filters, grouping and responsive alignment', async ({ page }) => {
  test.setTimeout(90_000);
  const recurring = ['initial', 'generated'].flatMap(phase => [ordinary, owned].map(row => ({
    ...row, id: `${row.id}-${phase}`, record_id: `${row.id}-${phase}`, receipt_count: 0,
    recurring_schedule_id: `${row.id}-schedule`, description: `Edited ${phase} memo`,
  })));
  const rows = [{ ...ordinary, description: 'Recurring monthly expense' }, owned, journal, ...recurring];
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    return route.fulfill({ json: url.pathname.endsWith('/ledger')
      ? { items: rows.filter(row => !url.searchParams.get('kind') || url.searchParams.get('kind') === 'All' || row.kind === url.searchParams.get('kind')) }
      : coreResponse(url) });
  });
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await page.goto('/transactions');
    const region = page.getByRole('region', { name: 'Ledger', exact: true });
    const header = region.getByRole('columnheader', { name: 'Type', exact: true });
    await expect(region.getByText('Recurring', { exact: true })).toHaveCount(4);
    await expect(region.getByRole('rowheader', { name: 'Expense · Recurring', exact: true })).toHaveCount(2);
    const mixed = region.getByRole('row').filter({ has: page.getByRole('rowheader', { name: 'Expense · Mixed-use · Recurring', exact: true }) });
    await expect(mixed).toHaveCount(2);
    await expect(mixed.getByRole('button', { name: /^Edit / })).toHaveCount(0);
    await expect(mixed.getByRole('link', { name: 'Manage mixed-use expense' })).toHaveCount(2);
    await expect(region.getByRole('rowheader', { name: 'Expense', exact: true })).toHaveCount(1);
    await expect(region.getByRole('rowheader', { name: 'Expense · Mixed-use', exact: true })).toHaveCount(1);
    await expect(region.getByRole('rowheader', { name: '↳ Posting', exact: true })).toHaveCount(2);
    const bounds = await header.boundingBox();
    for (const cell of await region.locator('tbody th[scope="row"]').all()) {
      const box = (await cell.boundingBox())!;
      expect(Math.abs(box.x - bounds!.x)).toBeLessThanOrEqual(1);
      expect(Math.abs(box.width - bounds!.width)).toBeLessThanOrEqual(1);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await region.focus(); await page.keyboard.press('ArrowRight');
    await expect.poll(() => region.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
    await region.evaluate(element => { element.scrollLeft = 0; });
    expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([]);
    await captureEvidence(page, test.info(), `recurring-ledger-${width}.png`);
    await page.getByLabel('Sort entries by').selectOption('Type');
    await page.getByLabel('Type', { exact: true }).selectOption('Expense');
    await expect(region.getByRole('rowheader', { name: '↳ Posting', exact: true })).toHaveCount(0);
    await expect(region.getByText('Recurring', { exact: true })).toHaveCount(4);
    await expect(page.getByLabel('Type', { exact: true }).getByRole('option')).toHaveText(['All', 'Income', 'Expense', 'Transfer', 'Journal']);
  }
});
