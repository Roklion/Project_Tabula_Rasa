import { defineConfig } from '@playwright/test';

// Node HTTP/Git contracts: no browser fixture, engine installation or dev SPA.
export default defineConfig({
  testDir: './contracts',
  workers: 1,
  outputDir: 'test-results/contracts/artifacts',
  reporter: [['line'], ['junit', { outputFile: 'test-results/contracts/results.xml' }]],
});
