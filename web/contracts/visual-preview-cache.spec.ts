import { access, mkdir, mkdtemp, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createServer } from 'vite';
import { expect, test } from '@playwright/test';
import { startVisualPreview } from '../e2e/visual-preview-server';

test('concurrent previews retain dependencies and clean up after a Vite restart', async () => {
  const previews: Awaited<ReturnType<typeof startVisualPreview>>[] = [];
  const normal = await createServer({ configFile: resolve('vite.config.ts'),
    server: { host: '127.0.0.1', port: 0 } });
  try {
    // Two preview lifetimes plus Playwright's normal dev server can overlap.
    // Keep the dependency request pending, as it can be during a browser load.
    for (let index = 0; index < 2; index++) {
      const preview = await startVisualPreview();
      previews.push(preview);
      preview.server.environments.client.config.dev.preTransformRequests = false;
    }
    const urls = await Promise.all(previews.map(async ({ server, origin }) => {
      const response = await fetch(new URL('/src/main.tsx', origin));
      expect(response.status).toBe(200);
      await server.waitForRequestsIdle();
      const optimizer = server.environments.client.depsOptimizer!;
      await optimizer.scanProcessing;
      await Promise.all(Object.values(optimizer.metadata.discovered).map(info => info.processing));
      const dependency = optimizer.metadata.optimized['react-dom/client'];
      return new URL(optimizer.getOptimizedDepId(dependency).replace(server.config.root, ''), origin);
    }));

    // Initialization invalidates a shared cache before replacement files are
    // committed. No sleeps, forced optimization or fake HTTP responses.
    await normal.environments.client.depsOptimizer!.init();
    for (const url of urls) {
      const response = await fetch(url);
      expect(response.status, response.statusText).toBe(200);
      expect(await response.text()).toContain('createRoot');
    }
    const caches = previews.map(({ server }) => server.config.cacheDir);
    expect(new Set([...caches, normal.config.cacheDir]).size).toBe(3);

    await previews[1].close();
    await expect(access(caches[1])).rejects.toMatchObject({ code: 'ENOENT' });
    await access(caches[0]);
    expect((await fetch(urls[0])).status).toBe(200);
    await previews[0].server.restart();
    expect((await fetch(new URL('/api/v1/session', previews[0].server.resolvedUrls!.local[0]))).status).toBe(200);
    await previews[0].close();
    await expect(access(caches[0])).rejects.toMatchObject({ code: 'ENOENT' });
  } finally {
    await Promise.all([...previews.map(({ close }) => close()), normal.close()]);
  }
});

test('failed preview startup removes its temporary optimizer cache', async () => {
  const root = await mkdtemp(join(tmpdir(), 'tabula-preview-startup-'));
  const previousDirectory = process.cwd();
  try {
    await mkdir(join(root, 'node_modules'));
    await writeFile(join(root, 'vite.visual-review.config.ts'),
      "throw new Error('Synthetic preview configuration failure'); export default {};");
    process.chdir(root);
    await expect(startVisualPreview()).rejects.toThrow('Synthetic preview configuration failure');
    expect(await readdir(join(root, 'node_modules'))).toEqual([]);
  } finally {
    process.chdir(previousDirectory);
    await rm(root, { recursive: true, force: true });
  }
});

test('cold HTTP-only preview drains optimization before cache cleanup', async () => {
  const preview = await startVisualPreview();
  const cacheDir = preview.server.config.cacheDir;
  try {
    expect((await fetch(new URL('/api/v1/session', preview.origin))).status).toBe(200);
    await preview.close();
    await expect(access(cacheDir)).rejects.toMatchObject({ code: 'ENOENT' });
  } finally { await preview.close(); }
});
