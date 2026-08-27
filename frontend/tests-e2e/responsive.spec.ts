import { expect, test } from "@playwright/test";

// STORY-049: real-browser responsive verification against the actual
// running local stack (see playwright.config.ts's own setup comment --
// requires the same seeded e2e_fixture jobs as search.spec.ts).

const WIDTHS = [320, 375, 768, 1024, 1440] as const;

async function hasNoHorizontalOverflow(page: import("@playwright/test").Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth
  );
}

test.describe("responsive layout", () => {
  for (const width of WIDTHS) {
    test(`no horizontal overflow at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      await expect(page.locator(".job-card").first()).toBeVisible();
      expect(await hasNoHorizontalOverflow(page)).toBe(true);

      await page.screenshot({
        path: `test-results/responsive-${width}.png`,
        fullPage: true,
      });
    });
  }

  test("search, filter, sort, and paginate remain usable at 320px", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 900 });
    await page.goto("/");
    await expect(page.locator(".job-card").first()).toBeVisible();

    // Pagination on the full, unfiltered 25-fixture result set (20/page).
    await expect(page.getByRole("button", { name: "Next" })).toBeEnabled();
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("button", { name: "Previous" })).toBeEnabled();
    expect(await hasNoHorizontalOverflow(page)).toBe(true);
    await page.getByRole("button", { name: "Previous" }).click();

    await page.locator("#q").fill("Principal Distributed Systems Engineer");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.locator(".job-card")).toHaveCount(1);
    expect(await hasNoHorizontalOverflow(page)).toBe(true);

    const remoteCheckbox = page.getByRole("checkbox", { name: "Remote" });
    await remoteCheckbox.click();
    await expect(remoteCheckbox).toBeChecked();
    await expect(page.locator(".job-card")).toHaveCount(1);
    expect(await hasNoHorizontalOverflow(page)).toBe(true);

    await page.locator("#sort").selectOption("posting_date");
    await expect(page).toHaveURL(/sort=posting_date/);
    expect(await hasNoHorizontalOverflow(page)).toBe(true);
  });
});
