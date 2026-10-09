import type { Schemas } from '../../api/client';

// Entry feedback only. The service remains the authoritative balance validator.
export function journalTotals(postings: Schemas['Posting'][]) {
  let debit = 0n, credit = 0n;
  let valid = postings.length >= 2;
  for (const line of postings) {
    const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(line.amount);
    if (!match || !line.target_id || !['Debit', 'Credit'].includes(line.side)) { valid = false; continue; }
    const cents = BigInt(match[1]) * 100n + BigInt((match[2] ?? '').padEnd(2, '0'));
    if (cents <= 0n) valid = false;
    if (line.side === 'Debit') debit += cents;
    else credit += cents;
  }
  const format = (value: bigint) => `${value < 0n ? '-' : ''}${(value < 0n ? -value : value) / 100n}.${((value < 0n ? -value : value) % 100n).toString().padStart(2, '0')}`;
  return { debit: format(debit), credit: format(credit), difference: format(debit - credit), balanced: valid && debit === credit };
}
