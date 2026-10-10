import { expect, it } from 'vitest';
import { mileageCsvCell } from './mileageCsv';

it('exports formula-leading user text as literal spreadsheet cells', () => {
  for (const value of ['=HYPERLINK("https://example.test")', '+SUM(A1:A2)', '-1+2', '@SUM(A1)', '  =1+1', '\t=1+1', '\r=1+1', '\ntext']) {
    expect(mileageCsvCell(value).startsWith('"\'')).toBe(true);
  }
  expect(mileageCsvCell('Office, "north"')).toBe('"Office, ""north"""');
  expect(mileageCsvCell('12.4')).toBe('"12.4"');
  expect(mileageCsvCell('2026-10-08')).toBe('"2026-10-08"');
});
