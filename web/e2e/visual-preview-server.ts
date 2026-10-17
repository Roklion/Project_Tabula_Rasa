import { createServer } from 'vite';
import { resolve } from 'node:path';

export async function startVisualPreview() {
  const server = await createServer({ configFile: resolve('vite.visual-review.config.ts'),
    server: { host: '127.0.0.1', port: 0,
      // Even an accidentally retained proxy cannot receive a preview request.
      proxy: { '/api': { target: 'http://127.0.0.1:1' } } },
  });
  await server.listen();
  return { server, origin: server.resolvedUrls!.local[0] };
}
