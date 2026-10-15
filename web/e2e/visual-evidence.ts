import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { platform } from 'node:os';
import { resolve } from 'node:path';
import { type Page, type TestInfo } from '@playwright/test';

type Capture = {
  filename: string; sha256: string; route: string; viewport: ReturnType<Page['viewportSize']>;
  browser: string; browserVersion: string; deviceScaleFactor: number;
  reflow: string; capturedAt: string;
};
const captures = new WeakMap<TestInfo, Capture[]>();
const hash = (bytes: string | Buffer) => createHash('sha256').update(bytes).digest('hex');
const git = (...args: string[]) => execFileSync('git', args, { encoding: 'utf8' }).trim();

// Hash only public application/harness sources, never local configuration or data.
export async function sourceHash(root = git('rev-parse', '--show-toplevel')) {
  const paths = git('-C', root, 'ls-files', '--cached', '--others', '--exclude-standard', '--',
    'web/index.html', 'web/public', 'web/src', 'web/e2e', 'web/package.json', 'web/package-lock.json', 'web/playwright.config.ts', 'web/vite.config.ts', 'web/visual-review.ts')
    .split('\n').filter(Boolean).sort();
  const digest = createHash('sha256');
  if (!paths.length) throw new Error('Visual evidence requires application and harness sources.');
  for (const path of paths) {
    digest.update(path + '\0');
    digest.update(await readFile(resolve(root, path)));
    digest.update('\0');
  }
  return digest.digest('hex');
}

export async function captureEvidence(page: Page, info: TestInfo, filename: string, reflow = 'native CSS viewport; browser zoom unchanged') {
  await page.evaluate(() => document.fonts.ready);
  const bytes = await page.screenshot({ path: info.outputPath(filename), fullPage: true, animations: 'disabled' });
  const browser = page.context().browser()!;
  const entry: Capture = {
    filename, sha256: hash(bytes), route: new URL(page.url()).pathname, viewport: page.viewportSize(),
    browser: browser.browserType().name(), browserVersion: browser.version(),
    deviceScaleFactor: await page.evaluate(() => window.devicePixelRatio), reflow, capturedAt: new Date().toISOString(),
  };
  captures.set(info, [...(captures.get(info) ?? []), entry]);
}

export async function retainEvidence(info: TestInfo) {
  const screenshots = captures.get(info) ?? [];
  // Keep manifests for failures and tests without screenshots as well.
  await mkdir(info.outputPath('.'), { recursive: true });
  const metadata = {
    schema: 1, revision: git('rev-parse', 'HEAD'), worktreeChanges: git('status', '--porcelain'),
    sourceSha256: await sourceHash(), project: info.project.name, platform: platform(),
    test: info.title, status: info.status, retry: info.retry, screenshots,
    data: 'Synthetic intercepted transport only; no live services, credentials, ledger or receipt bytes.',
    assessment: 'Automated evidence; visual/manual/device acceptance is recorded separately.',
  };
  await writeFile(info.outputPath('revision.json'), JSON.stringify(metadata, null, 2));
  captures.delete(info);
}
