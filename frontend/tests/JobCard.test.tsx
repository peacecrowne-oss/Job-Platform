import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { JobCard } from "@/components/JobCard";
import type { JobSearchResult } from "@/lib/searchApi";

function job(overrides: Partial<JobSearchResult> = {}): JobSearchResult {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    source: "greenhouse",
    job_title: "Senior Backend Engineer",
    company_name: "Acme Corp",
    location_city: "Berlin",
    location_region: "Berlin",
    location_country: "Germany",
    work_mode: "remote",
    employment_type: "full_time",
    seniority: "Senior",
    department: "Engineering",
    posting_date: "2026-01-15",
    source_url: "https://example.com/jobs/1",
    application_url: "https://example.com/apply/1",
    ...overrides,
  };
}

describe("JobCard", () => {
  it("renders title, company, and location", () => {
    render(<JobCard job={job()} />);
    expect(screen.getByText("Senior Backend Engineer")).toBeTruthy();
    expect(screen.getByText("Acme Corp")).toBeTruthy();
    expect(screen.getByText("Berlin, Berlin, Germany")).toBeTruthy();
  });

  it("renders work mode, employment type, seniority, and department tags", () => {
    render(<JobCard job={job()} />);
    expect(screen.getByText("Remote")).toBeTruthy();
    expect(screen.getByText("Full-time")).toBeTruthy();
    expect(screen.getByText("Senior")).toBeTruthy();
    expect(screen.getByText("Engineering")).toBeTruthy();
  });

  it("renders both source and application links", () => {
    render(<JobCard job={job()} />);
    const sourceLink = screen.getByText(/View original posting/) as HTMLAnchorElement;
    const applyLink = screen.getByText(/Apply/) as HTMLAnchorElement;
    expect(sourceLink.getAttribute("href")).toBe("https://example.com/jobs/1");
    expect(sourceLink.getAttribute("target")).toBe("_blank");
    expect(sourceLink.getAttribute("rel")).toBe("noopener noreferrer");
    expect(applyLink.getAttribute("href")).toBe("https://example.com/apply/1");
  });

  it("omits absent optional fields rather than showing a placeholder", () => {
    render(
      <JobCard
        job={job({
          company_name: null,
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
        })}
      />
    );
    expect(screen.queryByText("Acme Corp")).toBeNull();
    expect(screen.queryByText(/View original posting/)).toBeNull();
    expect(screen.queryByText(/Apply/)).toBeNull();
    expect(screen.getByText("Senior Backend Engineer")).toBeTruthy();
  });

  it("renders a partial location line when only some parts are present", () => {
    render(<JobCard job={job({ location_region: null, location_city: null })} />);
    expect(screen.getByText("Germany")).toBeTruthy();
  });

  it("falls back to an untitled label when job_title is null", () => {
    render(<JobCard job={job({ job_title: null })} />);
    expect(screen.getByText("Untitled role")).toBeTruthy();
  });

  it("does not render a link with a javascript: scheme", () => {
    render(<JobCard job={job({ source_url: "javascript:alert(1)", application_url: null })} />);
    expect(screen.queryByText(/View original posting/)).toBeNull();
  });
});
