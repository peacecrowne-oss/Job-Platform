import { expect, test } from "@playwright/test";

// STORY-034: navigation from search results into the job detail page, and
// the detail page's own rendering, against the real Docker Compose stack
// (backend + frontend + Postgres). Requires the same seeded e2e_fixture
// jobs as search.spec.ts (see playwright.config.ts's own setup comment).

const DISTINCTIVE_TITLE = "Principal Distributed Systems Engineer";
const DISTINCTIVE_SOURCE_URL = "https://example.com/jobs/e2e-fixture-distinctive";

test.describe("job detail page", () => {
  test("navigates from a search result to its detail page and renders real data", async ({
    page,
  }) => {
    await page.goto("/");
    await page.locator("#q").fill(DISTINCTIVE_TITLE);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.locator(".job-card")).toHaveCount(1);

    await page.getByRole("link", { name: DISTINCTIVE_TITLE }).click();

    await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: DISTINCTIVE_TITLE, level: 1 })).toBeVisible();

    const sourceLink = page.getByRole("link", { name: /View original posting/ });
    await expect(sourceLink).toHaveAttribute("href", DISTINCTIVE_SOURCE_URL);
  });

  test("shows a real HTTP 404 for a nonexistent job id", async ({ page }) => {
    const response = await page.goto("/jobs/00000000-0000-0000-0000-000000000000");
    expect(response?.status()).toBe(404);
  });
});
