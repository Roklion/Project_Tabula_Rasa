import { defineConfig, devices } from '@playwright/test';

const port = Number(process.env.TABULA_RASA_SMOKE_PORT ?? '5173');
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid browser smoke port.');
const origin = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  workers: process.env.CI ? 2 : undefined,
  use: { baseURL: origin, trace: 'retain-on-failure' },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: origin, reuseExistingServer: false,
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium', viewport: { width: 390, height: 844 } } },
    { name: 'firefox', use: { browserName: 'firefox', viewport: { width: 1440, height: 1000 } } },
    { name: 'webkit', use: { browserName: 'webkit', viewport: { width: 390, height: 844 } } },
  ],
});
