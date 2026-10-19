import { createServer, type ViteDevServer } from 'vite';
import { mkdtemp, rm } from 'node:fs/promises';
import { resolve } from 'node:path';

export async function startVisualPreview() {
  // Vite removes/replaces its optimizer cache on config changes. Each live
  // preview needs its own cache, including previews in the same worker.
  const cacheDir = await mkdtemp(resolve('node_modules/.vite-visual-'));
  let server: ViteDevServer | undefined;
  // Keep lifetime ownership outside Vite: restart replaces server methods.
  const close = async () => {
    try {
      if (server) {
        // Vite can finish close while a cold scan has handed off a build.
        // Drain that work before shutdown and removing its output directory.
        const client = server.environments.client;
        await client.waitForRequestsIdle();
        const optimizer = client.depsOptimizer;
        await optimizer?.scanProcessing;
        await Promise.all(Object.values(optimizer?.metadata.discovered ?? {}).map(info => info.processing));
        await server.close();
      }
    } finally { await rm(cacheDir, { recursive: true, force: true }); }
  };
  try {
    server = await createServer({ configFile: resolve('vite.visual-review.config.ts'), cacheDir,
      server: { host: '127.0.0.1', port: 0,
        // Even an accidentally retained proxy cannot receive a preview request.
        proxy: { '/api': { target: 'http://127.0.0.1:1' } } },
    });
    await server.listen();
    return { server, origin: server.resolvedUrls!.local[0], close };
  } catch (error) {
    await close();
    throw error;
  }
}
