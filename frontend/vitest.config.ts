import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  test: {
    // STORY-035: component tests need a DOM. "node" (the STORY-013
    // default) is kept for lib/config.ts's pure-logic tests, which don't
    // need one -- jsdom works for both.
    environment: "jsdom",
    // The default "forks" pool hangs indefinitely on this Windows
    // environment (observed: a worker-timeout error with zero tests run).
    // "threads" runs reliably here.
    pool: "threads",
    setupFiles: ["./vitest.setup.ts"],
    // STORY-054: tests-e2e/ holds Playwright specs (a separate runner,
    // `npm run e2e`) -- Vitest's default include glob would otherwise also
    // try to collect and run them as Vitest tests and fail on the
    // `@playwright/test` imports.
    exclude: ["**/node_modules/**", "**/tests-e2e/**"],
  },
  resolve: {
    // Vitest/Vite don't read tsconfig.json's "paths" automatically --
    // mirror the "@/*" alias Next.js already resolves at build time.
    alias: {
      "@": rootDir,
    },
  },
});
