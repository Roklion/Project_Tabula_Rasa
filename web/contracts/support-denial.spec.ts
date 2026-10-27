import { expect, test } from '@playwright/test';
import type { Browser, Route } from '@playwright/test';
import { guard, main, run, validateTarget } from '../support-denial';

const target = { origin: 'https://synthetic.invalid', release: 'a'.repeat(40),
  organization: 'org-a', business: 'business-a', approval: 'private-approval-ref', synthetic: true, consent: true };

test('target approval and consent are mandatory before launching or making requests', async () => {
  for (const delta of [{ consent: false }, { synthetic: false }, { approval: '' },
    { origin: 'http://synthetic.invalid' }, { origin: 'https://user:secret@synthetic.invalid' },
    { origin: 'https://synthetic.invalid/path' }, { release: 'main' }, { business: '../business-b' }]) {
    let launches = 0;
    await expect(run({ ...target, ...delta }, async () => { launches++; throw Error('secret'); },
      async () => true)).rejects.toThrow();
    expect(launches).toBe(0);
  }
  expect(() => validateTarget(target)).not.toThrow();
});

test('interactive refusal and probe exceptions close both context and browser', async () => {
  for (const consent of [false, true]) {
    const actions: string[] = [];
    const browser = { newContext: async (options: unknown) => {
      expect(options).toEqual({ acceptDownloads: false, serviceWorkers: 'block' });
      return { route: async () => {}, newPage: async () => ({ goto: async () => {},
        evaluate: async () => { actions.push('probe'); throw Error('SENTINEL-secret'); } }),
      close: async () => { actions.push('context-closed'); } };
    }, close: async () => { actions.push('browser-closed'); } } as unknown as Browser;
    await expect(run(target, async () => browser, async () => consent)).rejects.toThrow();
    expect(actions).toEqual([...(consent ? ['probe'] : []), 'context-closed', 'browser-closed']);
  }
});

test('traffic guard blocks financial reads and writes, permitting only one diagnostics POST', async () => {
  let remaining = 1;
  const diagnostics = '/api/v1/support/org-a/business-a/diagnostics';
  const decisions: string[] = [];
  for (const [path, method] of [['/api/v1/entities/business-a/accounts', 'GET'],
    ['/api/v1/entities/business-a/transactions', 'POST'], ['/api/v1/support/org-b/business-b/diagnostics', 'POST'],
    [diagnostics, 'POST'], [diagnostics, 'POST'], ['/api/v1/session', 'GET'], ['/api/v1/session/entity', 'POST']]) {
    const route = { request: () => ({ url: () => target.origin + path, method: () => method }),
      continue: async () => { decisions.push('allowed'); }, abort: async () => { decisions.push('blocked'); } };
    await guard(route as unknown as Route, target.origin, diagnostics, () => remaining-- === 1);
  }
  expect(decisions).toEqual(['blocked', 'blocked', 'blocked', 'allowed', 'blocked', 'allowed', 'allowed']);
});

test('CLI failures never echo arguments, credentials or exceptions', async () => {
  const output: string[] = [];
  const log = console.log;
  console.log = value => output.push(String(value));
  try {
    expect(await main(['--cookie', 'SENTINEL-secret'])).toBe(1);
    expect(await main(['--origin', 'https://SENTINEL-secret@synthetic.invalid'])).toBe(1);
  } finally { console.log = log; }
  expect(output).toEqual(Array(2).fill(JSON.stringify({ status: 'refused', release: null,
    request_id: null, collector_and_notification: 'unverified' })));
});
