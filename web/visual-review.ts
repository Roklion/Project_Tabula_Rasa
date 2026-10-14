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
        if (request.method !== 'GET' || !url.pathname.startsWith('/api/v1/')) {
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
