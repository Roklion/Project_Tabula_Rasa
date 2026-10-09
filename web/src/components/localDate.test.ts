import { expect, it, vi } from 'vitest';
import { localDate } from './localDate';

it('formats the local calendar date for date inputs without locale display formatting', () => {
  const locale = vi.spyOn(Date.prototype, 'toLocaleDateString').mockReturnValue('01/02/2026');
  try {
    expect(localDate(new Date(2026, 0, 2, 0, 1))).toBe('2026-01-02');
    expect(localDate(new Date(2026, 11, 31, 23, 59))).toBe('2026-12-31');
    expect(locale).not.toHaveBeenCalled();
  } finally { locale.mockRestore(); }
});
