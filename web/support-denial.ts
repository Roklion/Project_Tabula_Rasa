// Opt-in operator client. Never imported by the product bundle.
import { parseArgs } from 'node:util';
import { pathToFileURL } from 'node:url';
import { createInterface } from 'node:readline/promises';
import type { Browser, Route } from '@playwright/test';

export type Target = { origin: string; release: string; organization: string; business: string;
  approval: string; synthetic: boolean; consent: boolean };
export type Outcome = { status: 'expected_forbidden' | 'refused'; release: string | null;
  request_id: string | null; collector_and_notification: 'unverified' };

export function validateTarget(target: Target) {
  const url = new URL(target.origin);
  if (url.protocol !== 'https:' || url.origin !== target.origin || url.username || url.password
    || !/^[a-f0-9]{40}$/.test(target.release)
    || ![target.organization, target.business, target.approval].every(v => /^[A-Za-z0-9_-]{1,200}$/.test(v))
    || target.synthetic !== true || target.consent !== true) throw new Error('refused');
}

// Runs entirely in the ephemeral page: session/CSRF never crosses the automation boundary.
// Keep this self-contained so Playwright can serialize it without a bundled helper.
export async function probe(target: Target): Promise<Outcome> {
  const result: Outcome = { status: 'refused', release: null, request_id: null,
    collector_and_notification: 'unverified' };
  try {
    if (location.origin !== target.origin || !target.synthetic || !target.consent) return result;
    const read = async (path: string, status: number, init: RequestInit = {}) => {
      const response = await fetch(target.origin + path, { ...init, credentials: 'same-origin',
        redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(15000) });
      if (response.status !== status || response.url !== target.origin + path || response.redirected
        || response.headers.get('content-type')?.split(';')[0].trim() !== 'application/json'
        || !response.body) {
        await response.body?.cancel();
        throw new Error('refused');
      }
      const reader = response.body.getReader();
      const chunks: Uint8Array[] = [];
      let size = 0;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.length;
          if (size > 65536) throw new Error('refused');
          chunks.push(value);
        }
      } finally { await reader.cancel(); }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      return { response, data: JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) };
    };
    const version = await read('/version', 200);
    if (version.response.status !== 200 || version.data.release !== target.release
      || !/^[a-f0-9]{40}$/.test(version.data.release)) return result;
    result.release = version.data.release;
    const { response, data: session } = await read('/api/v1/session', 200);
    if (response.status !== 200 || session.state !== 'ready' || session.trusted_development !== false
      || typeof session.actor_id !== 'string' || !session.actor_id
      || typeof session.cache_scope !== 'string' || !session.cache_scope
      || !Array.isArray(session.capabilities) || !session.capabilities.every((v: unknown) => typeof v === 'string')
      || session.organization_id !== target.organization || session.entity?.id !== target.business
      // NamedIdentity.info owns these claims; alpha context_info omits them.
      || session.entity.organization_id !== target.organization
      || !['owner', 'admin', 'editor', 'accountant', 'read_only'].includes(session.entity.role)
      || typeof session.csrf_token !== 'string' || !/^[\x21-\x7e]{1,512}$/.test(session.csrf_token)) return result;
    const denial = await read(`/api/v1/support/${target.organization}/${target.business}/diagnostics`, 403, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token },
      body: JSON.stringify({ reason: 'incident' }),
    }); // Browser supplies Origin and cookies. No retry, even after an uncertain response.
    const data = denial.data;
    if (denial.response.status !== 403 || data?.error?.code !== 'forbidden'
      || data.error.message !== 'You do not have access to this operation.'
      || Object.keys(data).sort().join(',') !== 'error,request_id'
      || Object.keys(data.error).sort().join(',') !== 'code,message'
      || typeof data.request_id !== 'string' || !/^[a-f0-9]{32}$/.test(data.request_id)
      || denial.response.headers.get('x-request-id') !== data.request_id) return result;
    result.status = 'expected_forbidden';
    result.request_id = data.request_id;
  } catch { /* Never return exception, body, URL, headers or submitted values. */ }
  return result;
}

// Login and scope selection only; prevent the ordinary SPA from reading financial data
// or performing unrelated mutations while the human completes login/MFA.
export async function guard(route: Route, origin: string, diagnostics: string, takePost: () => boolean) {
  const request = route.request();
  const url = new URL(request.url());
  if (url.origin !== origin) return route.continue(); // Interactive identity provider.
  const path = url.pathname;
  const method = request.method();
  const get = method === 'GET' && (['/version', '/api/v1/session', '/api/v1/businesses',
    '/api/v1/entities', '/api/v1/auth/login', '/api/v1/auth/callback'].includes(path)
    || !path.startsWith('/api/'));
  const selection = method === 'POST' && path === '/api/v1/session/entity';
  const post = method === 'POST' && path === diagnostics && takePost();
  if (get || selection || post) return route.continue();
  return route.abort('blockedbyclient');
}

export async function run(target: Target, launch: () => Promise<Browser>, confirm: () => Promise<boolean>) {
  validateTarget(target); // No browser/network until explicit approval attestation and consent.
  const browser = await launch();
  try {
    const context = await browser.newContext({ acceptDownloads: false, serviceWorkers: 'block' });
    try {
      let budget = 0;
      await context.route('**/*', route => guard(route, target.origin,
        `/api/v1/support/${target.organization}/${target.business}/diagnostics`, () => {
          if (budget !== 1) return false;
          budget = 0;
          return true;
        }));
      const page = await context.newPage();
      await page.goto(target.origin + '/api/v1/auth/login');
      if (!await confirm()) throw new Error('refused');
      budget = 1;
      return await page.evaluate(probe, target);
    } finally { await context.close(); }
  } finally { await browser.close(); }
}

export async function main(argv = process.argv.slice(2)) {
  let result: Outcome = { status: 'refused', release: null, request_id: null,
    collector_and_notification: 'unverified' };
  try {
    // Refuse diagnostic runtime modes before importing Playwright. Never enable
    // runner fixtures/reporters, trace/HAR/video, inspector, screenshots or raw logs.
    if (process.execArgv.length || Object.keys(process.env).some(k => /^(DEBUG|PWDEBUG|NODE_DEBUG|NODE_OPTIONS|PW_LOG_NAME|PLAYWRIGHT_)/.test(k)
      && process.env[k])) throw new Error('refused');
    const { values } = parseArgs({ args: argv, options: {
      origin: { type: 'string' }, release: { type: 'string' }, organization: { type: 'string' },
      business: { type: 'string' }, approval: { type: 'string' },
      'synthetic-approved': { type: 'boolean' }, 'consent-one-request': { type: 'boolean' },
    } });
    const target = { origin: values.origin ?? '', release: values.release ?? '',
      organization: values.organization ?? '', business: values.business ?? '', approval: values.approval ?? '',
      synthetic: values['synthetic-approved'] === true, consent: values['consent-one-request'] === true };
    validateTarget(target);
    if (!process.stdin.isTTY || !process.stdout.isTTY) throw new Error('refused');
    const { chromium } = await import('@playwright/test');
    result = await run(target, () => chromium.launch({ headless: false }), async () => {
      const terminal = createInterface({ input: process.stdin, output: process.stdout });
      try {
        return await terminal.question('Complete ordinary login/MFA and select the approved business. '
          + 'Confirm the external exact-target/window approval and no support grant. '
          + 'Type SEND ONE DIAGNOSTICS REQUEST to consent: ') === 'SEND ONE DIAGNOSTICS REQUEST';
      } finally { terminal.close(); }
    });
  } catch { /* Fixed output only, including launch/login/teardown failures. */ }
  console.log(JSON.stringify(result));
  return result.status === 'expected_forbidden' ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
