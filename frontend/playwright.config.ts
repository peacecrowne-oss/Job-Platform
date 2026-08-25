import { defineConfig, devices } from "@playwright/test";

// STORY-054: runs against the real local Docker Compose stack (frontend +
// backend + Postgres + Redis all already up), not a Playwright-managed dev
// server -- per the approved plan's own instruction to exercise "the real
// local stack". Requires:
//   1. `docker compose up -d` (repo root)
//   2. `python backend/scripts/seed_e2e_fixtures.py` (seeds deterministic
//      fixture jobs tagged source="e2e_fixture")
//   3. `npm run e2e` (this directory)
//   4. `python backend/scripts/seed_e2e_fixtures.py --cleanup` afterward
export default defineConfig({
  testDir: "./tests-e2e",
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },
  // Chromium only -- the smallest setup that satisfies the Story's own
  // literal requirement; widening to Firefox/WebKit is a trivial addition
  // later if ever needed, not a redesign.
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
