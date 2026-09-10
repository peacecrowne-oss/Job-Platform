import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// STORY-048: automated WCAG 2.1 A/AA checks against the real rendered
// stack (backend + frontend + Postgres) for the two flows that actually
// exist -- search and job detail. Auth (STORY-036) and saved jobs
// (STORY-038) aren't built yet, matching the same "don't test nonexistent
// UI" precedent search.spec.ts already established for STORY-054.
//
// Requires the fixture jobs from backend/scripts/seed_e2e_fixtures.py
// already seeded into the real local Docker Compose stack's database
// (see playwright.config.ts's own setup comment).

const DISTINCTIVE_TITLE = "Principal Distributed Systems Engineer";
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

test.describe("accessibility", () => {
  test("search page has no automated WCAG 2.1 A/AA violations", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".job-card").first()).toBeVisible();

    const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
    expect(results.violations).toEqual([]);
  });

  test("the results region is a live region that reflects state changes", async ({ page }) => {
    // Edge case: dynamically loaded content announces updates to screen
    // readers -- verified by asserting the live region itself exists and
    // its content reflects the loaded results, not just re-reading the
    // markup.
    await page.goto("/");
    const resultsRegion = page.locator('[aria-live="polite"]');
    await expect(resultsRegion).toHaveAttribute("aria-live", "polite");
    await expect(resultsRegion.locator(".job-card").first()).toBeVisible();
  });

  test("job detail page has no automated WCAG 2.1 A/AA violations", async ({ page }) => {
    await page.goto("/");
    await page.locator("#q").fill(DISTINCTIVE_TITLE);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.locator(".job-card")).toHaveCount(1);

    await page.getByRole("link", { name: DISTINCTIVE_TITLE }).click();
    await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: DISTINCTIVE_TITLE, level: 1 })).toBeVisible();

    const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
    expect(results.violations).toEqual([]);
  });

  test("external link accessible names don't include decorative arrow noise", async ({
    page,
  }) => {
    await page.goto("/");
    await page.locator("#q").fill(DISTINCTIVE_TITLE);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await page.getByRole("link", { name: DISTINCTIVE_TITLE }).click();

    const applyLink = page.getByRole("link", { name: "Apply" });
    await expect(applyLink).toBeVisible();
    // The decorative arrow glyph is aria-hidden -- the accessible name is
    // exactly "Apply", not "Apply ↗".
    await expect(applyLink).toHaveAccessibleName("Apply");
  });
});
