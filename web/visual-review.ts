import type { Plugin } from 'vite';
import { coreResponse } from './e2e/core-fixture.ts';
import { secondaryResponse } from './e2e/secondary-fixture.ts';

// Opt-in local preview only. The browser suites use these same response owners.
// Register before Vite's API proxy, and terminate EVERY /api request here.
export function visualReview(): Plugin {
  return {
    name: 'synthetic-visual-review',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const url = new URL(request.url ?? '/', 'http://synthetic.invalid');
        if (!url.pathname.startsWith('/api')) return next();
        response.setHeader('Content-Type', 'application/json');
        response.setHeader('Cache-Control', 'no-store');
        const supported = url.pathname === '/api/v1/session' || url.pathname === '/api/v1/entities'
          || /^\/api\/v1\/entities\/[^/]+\/(?:reports\/summary|ledger|accounts|categories|payees|tags|transactions|journals|mixed-use|recurring|assets|assets\/types|mileage|mileage\/maps|documents)$/.test(url.pathname)
          || /^\/api\/v1\/entities\/[^/]+\/(?:mixed-use|recurring|assets|mileage)\/[^/]+$/.test(url.pathname)
          || /^\/api\/v1\/entities\/[^/]+\/(?:transactions|mixed-use)\/[^/]+\/receipts$/.test(url.pathname);
        const postOnly = /^\/api\/v1\/entities\/[^/]+\/(?:mixed-use\/allocation|mixed-use\/[^/]+\/copy-draft|mileage\/routes)$/.test(url.pathname);
        const preparation = request.method === 'POST'
          && /^\/api\/v1\/entities\/[^/]+\/mixed-use\/(?:allocation|[^/]+\/copy-draft)$/.test(url.pathname);
        if (!preparation && (request.method !== 'GET' || !supported || postOnly)) {
          response.statusCode = 405;
          response.end(JSON.stringify({ error: { code: 'unavailable' }, request_id: 'synthetic-preview-read-only' }));
          return;
        }
        const financial = /\/(?:reports\/summary|ledger)$/.test(url.pathname);
        response.end(JSON.stringify(financial ? coreResponse(url) : secondaryResponse(url)));
      });
    },
  };
}
