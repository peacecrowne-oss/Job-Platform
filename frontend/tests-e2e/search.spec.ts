import { expect, test } from "@playwright/test";

// STORY-054: the one currently-built "core user flow" (search) per the
// literal AC's own "once built" qualifier -- auth (STORY-036) doesn't
// exist in this repository yet, so no E2E test is written against
// nonexistent UI for it. Job detail (STORY-034) now exists -- see the
// separate job-detail.spec.ts for its own navigation/rendering coverage.
//
// Requires the fixture jobs from backend/scripts/seed_e2e_fixtures.py
// already seeded into the real local Docker Compose stack's database
// (see playwright.config.ts's own setup comment).

const DISTINCTIVE_TITLE = "Principal Distributed Systems Engineer";
const DISTINCTIVE_SOURCE_URL = "https://example.com/jobs/e2e-fixture-distinctive";

test.describe("job search", () => {
  test("search, filter, sort, paginate, and verify a safe link against seeded fixtures", async ({
    page,
  }) => {
    // 1 & 2: open the UI, see seeded jobs.
    await page.goto("/");
    await expect(page.locator(".job-card").first()).toBeVisible();
    await expect(page.getByText("Fixture Systems Inc").first()).toBeVisible();

    // Pagination: 25 fixture jobs, 20 per page -- Next must be enabled and
    // actually change the visible page.
    const nextButton = page.getByRole("button", { name: "Next" });
    await expect(nextButton).toBeEnabled();
    const firstPageFirstTitle = await page.locator(".job-card__title").first().textContent();
    await nextButton.click();
    await expect(page.getByRole("button", { name: "Previous" })).toBeEnabled();
    const secondPageFirstTitle = await page.locator(".job-card__title").first().textContent();
    expect(secondPageFirstTitle).not.toBe(firstPageFirstTitle);
    await page.getByRole("button", { name: "Previous" }).click();
    // Wait for the Previous click's own URL-state navigation to fully
    // settle before the next interaction -- otherwise the page's own
    // URL-driven `useEffect` (which resets `form.q` whenever the URL
    // changes) can race the very next fill() below and clobber it back
    // to empty right before Search is clicked, submitting an unfiltered
    // search instead. Pre-existing timing sensitivity in the app's own
    // state management, not something this Story's own changes caused --
    // fixed here as a test-only synchronization point.
    await expect(page).toHaveURL("/");

    // 3: submit a keyword matching exactly one fixture job.
    await page.locator("#q").fill(DISTINCTIVE_TITLE);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.locator(".job-card")).toHaveCount(1);
    await expect(page.locator(".job-card__title")).toHaveText(DISTINCTIVE_TITLE);

    // 4: apply a filter consistent with the matched job (work_mode=remote)
    // -- the result must remain present, proving search + filter compose.
    // `.click()` (not `.check()`) -- this is a React-controlled checkbox
    // that briefly re-renders around the URL-state navigation `onChange`
    // triggers, so `.check()`'s own strict single-shot "did state change"
    // assertion can see a transient unchecked frame; `toBeChecked()` below
    // polls with retries instead, tolerant of that render cycle.
    const remoteCheckbox = page.getByRole("checkbox", { name: "Remote" });
    await remoteCheckbox.click();
    await expect(remoteCheckbox).toBeChecked();
    await expect(page.locator(".job-card")).toHaveCount(1);
    await expect(page.locator(".job-card__title")).toHaveText(DISTINCTIVE_TITLE);

    // 5: change sort -- URL reflects it, the single matching result
    // remains (sorting changes ordering, not matching).
    await page.locator("#sort").selectOption("posting_date");
    await expect(page).toHaveURL(/sort=posting_date/);
    await expect(page.locator(".job-card__title")).toHaveText(DISTINCTIVE_TITLE);

    // 6: verify (not follow, to stay on the local stack) the safe source
    // link renders with the exact expected href.
    const sourceLink = page.getByRole("link", { name: /View original posting/ });
    await expect(sourceLink).toHaveAttribute("href", DISTINCTIVE_SOURCE_URL);
  });
});
