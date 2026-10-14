import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { visualReview } from './visual-review.ts';

const reviewMode = process.env.TABULA_RASA_VISUAL_REVIEW === '1';

export default defineConfig({
  plugins: [react(), ...(reviewMode ? [visualReview()] : [])],
  server: {
    host: '127.0.0.1',
    proxy: reviewMode ? undefined : { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  test: { include: ['src/**/*.test.{ts,tsx}'], environment: 'jsdom', setupFiles: ['./src/test/setup.ts'], restoreMocks: true },
});
