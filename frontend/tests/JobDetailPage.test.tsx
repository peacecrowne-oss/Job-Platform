import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import JobDetailPage from "@/app/jobs/[id]/page";
import * as jobApi from "@/lib/jobApi";
import type { JobDetail } from "@/lib/jobApi";

// JobDetailPage is an async Server Component -- not something JSX (`<Comp
// />`) can render directly in a test. Calling it as a plain async function
// and rendering the resolved element is the established way to test an
// App Router async Server Component with React Testing Library.
async function renderPage(id = "11111111-1111-1111-1111-111111111111") {
  const element = await JobDetailPage({ params: Promise.resolve({ id }) });
  render(element);
}

const notFoundMock = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});

vi.mock("next/navigation", () => ({
  notFound: () => notFoundMock(),
}));

function job(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    source: "greenhouse",
    source_url: "https://example.com/jobs/1",
    source_job_id: "123",
    company_name: "Acme Corp",
    job_title: "Senior Backend Engineer",
    description_full: "<p>Build the core platform.</p>",
    responsibilities: null,
    requirements: null,
    preferred_requirements: null,
    qualifications: null,
    skills: null,
    location_city: "Berlin",
    location_region: "Berlin",
    location_country: "Germany",
    work_mode: "remote",
    employment_type: "full_time",
    seniority: "Senior",
    department: "Engineering",
    compensation_min: null,
    compensation_max: null,
    compensation_currency: null,
    compensation_period: null,
    benefits: null,
    posting_date: "2026-01-15",
    closing_date: null,
    application_url: "https://example.com/apply/1",
    first_seen_at: "2026-01-15T00:00:00Z",
    last_seen_at: "2026-01-20T00:00:00Z",
    source_updated_at: null,
    closed_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000";
  notFoundMock.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("JobDetailPage", () => {
  it("renders title, company, and location", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(job());
    await renderPage();
    expect(screen.getByText("Senior Backend Engineer")).toBeTruthy();
    expect(screen.getByText("Acme Corp")).toBeTruthy();
    expect(screen.getByText("Berlin, Berlin, Germany")).toBeTruthy();
  });

  it("renders the description as real HTML formatting, not escaped text", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(
      job({ description_full: "<p>Real paragraph</p><ul><li>One</li></ul>" })
    );
    await renderPage();
    expect(screen.getByText("Real paragraph").tagName).toBe("P");
    expect(screen.getByText("One").tagName).toBe("LI");
  });

  it("omits a section entirely when its data is null", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(job({ responsibilities: null }));
    await renderPage();
    expect(screen.queryByText("Responsibilities")).toBeNull();
  });

  it("renders a section when its data is present", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(
      job({ responsibilities: "<p>Own the API layer.</p>" })
    );
    await renderPage();
    expect(screen.getByText("Responsibilities")).toBeTruthy();
    expect(screen.getByText("Own the API layer.")).toBeTruthy();
  });

  it("renders skills as a list when present", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(job({ skills: ["Python", "SQL"] }));
    await renderPage();
    expect(screen.getByText("Python")).toBeTruthy();
    expect(screen.getByText("SQL")).toBeTruthy();
  });

  it("omits the skills section when skills is null", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(job({ skills: null }));
    await renderPage();
    expect(screen.queryByText("Skills")).toBeNull();
  });

  it("renders compensation range with currency and period", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(
      job({
        compensation_min: "80000",
        compensation_max: "120000",
        compensation_currency: "USD",
        compensation_period: "year",
      })
    );
    await renderPage();
    expect(screen.getByText("80,000–120,000 USD / year")).toBeTruthy();
  });

  it("omits the compensation section when both min and max are null", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(
      job({ compensation_min: null, compensation_max: null })
    );
    await renderPage();
    expect(screen.queryByText("Compensation")).toBeNull();
  });

  it("shows a Closed badge when closed_at is set", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(job({ closed_at: "2026-02-01T00:00:00Z" }));
    await renderPage();
    expect(screen.getByText("Closed")).toBeTruthy();
  });

  it("does not show a Closed badge for an active job", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(job({ closed_at: null }));
    await renderPage();
    expect(screen.queryByText("Closed")).toBeNull();
  });

  it("renders safe external links with correct attributes", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(job());
    await renderPage();
    const applyLink = screen.getByText(/Apply/) as HTMLAnchorElement;
    expect(applyLink.getAttribute("href")).toBe("https://example.com/apply/1");
    expect(applyLink.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("does not render a link with a javascript: scheme", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(
      job({ source_url: "javascript:alert(1)", application_url: null })
    );
    await renderPage();
    expect(screen.queryByText(/View original posting/)).toBeNull();
    expect(screen.queryByText(/Apply/)).toBeNull();
  });

  it("calls notFound() when the job does not exist", async () => {
    vi.spyOn(jobApi, "getJob").mockResolvedValue(null);
    await expect(renderPage()).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFoundMock).toHaveBeenCalledTimes(1);
  });

  it("renders an inline error state when the fetch fails", async () => {
    vi.spyOn(jobApi, "getJob").mockRejectedValue(new jobApi.JobDetailError("failed"));
    await renderPage();
    expect(screen.getByText("Something went wrong loading this job.")).toBeTruthy();
  });

  it("renders a role=alert error message so it's announced to assistive tech", async () => {
    vi.spyOn(jobApi, "getJob").mockRejectedValue(new jobApi.JobDetailError("failed"));
    await renderPage();
    expect(screen.getByRole("alert")).toBeTruthy();
  });
});
