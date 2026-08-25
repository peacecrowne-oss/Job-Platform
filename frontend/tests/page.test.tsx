import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import HomePage from "@/app/page";
import * as searchApi from "@/lib/searchApi";
import type { JobSearchResponse } from "@/lib/searchApi";

const pushMock = vi.fn();
let currentParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => "/",
  useSearchParams: () => currentParams,
}));

function emptyResponse(overrides: Partial<JobSearchResponse> = {}): JobSearchResponse {
  return {
    query: null,
    limit: 20,
    offset: 0,
    has_next: false,
    has_previous: false,
    results: [],
    ...overrides,
  };
}

function job(id: string, overrides: Partial<JobSearchResponse["results"][number]> = {}) {
  return {
    id,
    source: "greenhouse",
    job_title: `Role ${id}`,
    company_name: "Acme Corp",
    location_city: null,
    location_region: null,
    location_country: null,
    work_mode: null,
    employment_type: null,
    seniority: null,
    department: null,
    posting_date: null,
    source_url: null,
    application_url: null,
    ...overrides,
  };
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000";
  pushMock.mockClear();
  currentParams = new URLSearchParams();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("HomePage", () => {
  it("renders the search form on initial render", () => {
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    render(<HomePage />);
    expect(screen.getByLabelText("Search")).toBeTruthy();
    expect(screen.getByText("Job Search")).toBeTruthy();
  });

  it("issues a default search on mount with no params", async () => {
    const spy = vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    render(<HomePage />);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(spy.mock.calls[0][0]).toMatchObject({ q: undefined, offset: 0 });
  });

  it("submits a keyword search and navigates with the query encoded", async () => {
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    const user = userEvent.setup();
    render(<HomePage />);

    await user.type(screen.getByLabelText("Search"), "engineer");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    const [url] = pushMock.mock.calls.at(-1)!;
    expect(url).toContain("q=engineer");
  });

  it("submits on Enter key within the search input", async () => {
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    const user = userEvent.setup();
    render(<HomePage />);

    const input = screen.getByLabelText("Search");
    await user.type(input, "engineer{Enter}");

    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    expect(pushMock.mock.calls.at(-1)![0]).toContain("q=engineer");
  });

  it("clears the search text and re-navigates", async () => {
    currentParams = new URLSearchParams("q=engineer");
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    const user = userEvent.setup();
    render(<HomePage />);

    await user.click(screen.getByRole("button", { name: "Clear search" }));

    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    expect(pushMock.mock.calls.at(-1)![0]).not.toContain("q=");
  });

  it("toggles a work_mode checkbox and navigates with it set", async () => {
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    const user = userEvent.setup();
    render(<HomePage />);

    await user.click(screen.getByLabelText("Remote"));

    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    expect(pushMock.mock.calls.at(-1)![0]).toContain("work_mode=remote");
  });

  it("supports multiple work_mode values selected together", async () => {
    currentParams = new URLSearchParams("work_mode=remote");
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    const user = userEvent.setup();
    render(<HomePage />);

    await user.click(screen.getByLabelText("Hybrid"));

    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    const url = pushMock.mock.calls.at(-1)![0] as string;
    expect(url).toContain("work_mode=remote");
    expect(url).toContain("work_mode=hybrid");
  });

  it("commits a text filter (seniority) on blur", async () => {
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    const user = userEvent.setup();
    render(<HomePage />);

    const seniorityInput = screen.getByLabelText("Seniority");
    await user.type(seniorityInput, "Senior");
    await user.tab();

    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    expect(pushMock.mock.calls.at(-1)![0]).toContain("seniority=Senior");
  });

  it("combines multiple filters in one navigation", async () => {
    currentParams = new URLSearchParams("work_mode=remote&seniority=Senior");
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    const user = userEvent.setup();
    render(<HomePage />);

    await user.type(screen.getByLabelText("Company"), "Acme");
    await user.tab();

    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    const url = pushMock.mock.calls.at(-1)![0] as string;
    expect(url).toContain("work_mode=remote");
    expect(url).toContain("seniority=Senior");
    expect(url).toContain("company=Acme");
  });

  it("changes sort and navigates with offset reset", async () => {
    currentParams = new URLSearchParams("offset=40");
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    const user = userEvent.setup();
    render(<HomePage />);

    await user.selectOptions(screen.getByLabelText("Sort"), "posting_date");

    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    const url = pushMock.mock.calls.at(-1)![0] as string;
    expect(url).toContain("sort=posting_date");
    expect(url).not.toContain("offset=");
  });

  it("resets offset to 0 after a new keyword search", async () => {
    currentParams = new URLSearchParams("offset=40");
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    const user = userEvent.setup();
    render(<HomePage />);

    await user.type(screen.getByLabelText("Search"), "engineer");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    expect(pushMock.mock.calls.at(-1)![0]).not.toContain("offset=");
  });

  it("navigates forward on Next and back on Previous", async () => {
    currentParams = new URLSearchParams("offset=20");
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(
      emptyResponse({ offset: 20, has_next: true, has_previous: true, results: [job("a")] })
    );
    const user = userEvent.setup();
    render(<HomePage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Next" })).toBeTruthy());
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    expect(pushMock.mock.calls.at(-1)![0]).toContain("offset=40");

    pushMock.mockClear();
    await user.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() => expect(pushMock).toHaveBeenCalled());
    // offset=0 is the default and is omitted from the URL entirely (a
    // clean "/" rather than "/?offset=0" -- see searchParamsFromState).
    expect(pushMock.mock.calls.at(-1)![0]).toBe("/");
  });

  it("shows a loading state while the request is in flight", async () => {
    let resolveFn: (value: JobSearchResponse) => void;
    const pending = new Promise<JobSearchResponse>((resolve) => {
      resolveFn = resolve;
    });
    vi.spyOn(searchApi, "searchJobs").mockReturnValue(pending);

    render(<HomePage />);

    expect(screen.getByText("Searching…")).toBeTruthy();
    // Page chrome stays present during loading -- not a blank page.
    expect(screen.getByLabelText("Search")).toBeTruthy();

    resolveFn!(emptyResponse());
    await waitFor(() => expect(screen.queryByText("Searching…")).toBeNull());
  });

  it("shows the no-results-at-all empty state for an unfiltered empty search", async () => {
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    render(<HomePage />);

    await waitFor(() =>
      expect(screen.getByText("No jobs are available right now.")).toBeTruthy()
    );
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
  });

  it("shows the no-matches empty state when a filter is active", async () => {
    currentParams = new URLSearchParams("q=zzznomatch");
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    render(<HomePage />);

    await waitFor(() =>
      expect(screen.getByText("No jobs found matching your search.")).toBeTruthy()
    );
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeTruthy();
  });

  it("shows an error state on a rejected request, without a blank page", async () => {
    vi.spyOn(searchApi, "searchJobs").mockRejectedValue(new searchApi.JobSearchError("failed"));
    render(<HomePage />);

    await waitFor(() =>
      expect(screen.getByText("Something went wrong loading job results.")).toBeTruthy()
    );
    // Page chrome stays present -- not a blank page.
    expect(screen.getByLabelText("Search")).toBeTruthy();
  });

  it("retries the same search when Retry is clicked", async () => {
    const spy = vi
      .spyOn(searchApi, "searchJobs")
      .mockRejectedValueOnce(new searchApi.JobSearchError("failed"))
      .mockResolvedValueOnce(emptyResponse());
    const user = userEvent.setup();
    render(<HomePage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy());
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });

  it("renders job cards with missing optional fields gracefully", async () => {
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(
      emptyResponse({ results: [job("a", { job_title: "Bare Role", company_name: null })] })
    );
    render(<HomePage />);

    await waitFor(() => expect(screen.getByText("Bare Role")).toBeTruthy());
  });

  it("renders an external source link with safe attributes", async () => {
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(
      emptyResponse({
        results: [job("a", { source_url: "https://example.com/job/a" })],
      })
    );
    render(<HomePage />);

    await waitFor(() => {
      const link = screen.getByText(/View original posting/) as HTMLAnchorElement;
      expect(link.getAttribute("href")).toBe("https://example.com/job/a");
      expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    });
  });

  it("initializes state from the URL on mount", async () => {
    currentParams = new URLSearchParams("q=engineer&work_mode=remote&sort=posting_date");
    const spy = vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    render(<HomePage />);

    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy.mock.calls[0][0]).toMatchObject({
      q: "engineer",
      workMode: ["remote"],
      sort: "posting_date",
    });
    expect((screen.getByLabelText("Search") as HTMLInputElement).value).toBe("engineer");
    expect((screen.getByLabelText("Remote") as HTMLInputElement).checked).toBe(true);
  });

  it("shows results count text derived from offset and result length", async () => {
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(
      emptyResponse({ offset: 20, results: [job("a"), job("b")] })
    );
    render(<HomePage />);

    await waitFor(() => expect(screen.getByText("Showing 21–22")).toBeTruthy());
  });

  it("Tab reaches the search input first, then the checkbox filters", async () => {
    vi.spyOn(searchApi, "searchJobs").mockResolvedValue(emptyResponse());
    const user = userEvent.setup();
    render(<HomePage />);

    await user.tab();
    expect(document.activeElement).toBe(screen.getByLabelText("Search"));

    await user.tab(); // Search submit button
    await user.tab(); // Clear search button
    await user.tab(); // first checkbox
    expect(document.activeElement).toBe(screen.getByLabelText("Remote"));
  });
});
