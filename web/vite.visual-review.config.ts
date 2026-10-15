import { defineConfig } from 'vite';
import base from './vite.config.ts';
import { visualReview } from './visual-review.ts';

// Explicit local preview entry point; never imported by the packaged build.
export default defineConfig({
  ...base,
  plugins: [base.plugins ?? [], visualReview()],
  server: { host: '127.0.0.1', proxy: undefined },
});
