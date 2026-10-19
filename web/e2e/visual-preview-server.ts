import { createServer, type ViteDevServer } from 'vite';
import { mkdtemp, rm } from 'node:fs/promises';
import { resolve } from 'node:path';

export async function startVisualPreview() {
  // Vite removes/replaces its optimizer cache on config changes. Each live
  // preview needs its own cache, including previews in the same worker.
  const cacheDir = await mkdtemp(resolve('node_modules/.vite-visual-'));
  let server: ViteDevServer | undefined;
  try {
    server = await createServer({ configFile: resolve('vite.visual-review.config.ts'), cacheDir,
      server: { host: '127.0.0.1', port: 0,
        // Even an accidentally retained proxy cannot receive a preview request.
        proxy: { '/api': { target: 'http://127.0.0.1:1' } } },
    });
    const close = server.close;
    server.close = async () => {
      try { await close(); }
      finally { await rm(cacheDir, { recursive: true, force: true }); }
    };
    await server.listen();
    return { server, origin: server.resolvedUrls!.local[0] };
  } catch (error) {
    try { await server?.close(); }
    finally { await rm(cacheDir, { recursive: true, force: true }); }
    throw error;
  }
}
