"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { JobCard } from "@/components/JobCard";
import {
  type EmploymentType,
  type JobSearchResponse,
  type WorkMode,
  searchJobs,
} from "@/lib/searchApi";
import {
  DEFAULT_LIMIT,
  EMPTY_SEARCH_STATE,
  hasActiveQueryOrFilters,
  searchParamsFromState,
  stateFromSearchParams,
  type SearchState,
} from "@/lib/searchParams";

const WORK_MODE_OPTIONS: { value: WorkMode; label: string }[] = [
  { value: "remote", label: "Remote" },
  { value: "hybrid", label: "Hybrid" },
  { value: "on_site", label: "On-site" },
];

const EMPLOYMENT_TYPE_OPTIONS: { value: EmploymentType; label: string }[] = [
  { value: "full_time", label: "Full-time" },
  { value: "part_time", label: "Part-time" },
  { value: "contract", label: "Contract" },
  { value: "temporary", label: "Temporary" },
  { value: "internship", label: "Internship" },
  { value: "apprenticeship", label: "Apprenticeship" },
  { value: "other", label: "Other" },
];

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Best match (default)" },
  { value: "relevance", label: "Relevance" },
  { value: "posting_date", label: "Newest" },
  { value: "last_seen", label: "Recently updated" },
];

type ResultsStatus = "loading" | "loaded" | "empty" | "error";

function SearchPageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const urlSearchParams = useSearchParams();

  const [form, setForm] = useState<SearchState>(() =>
    stateFromSearchParams(urlSearchParams)
  );
  const [response, setResponse] = useState<JobSearchResponse | null>(null);
  const [status, setStatus] = useState<ResultsStatus>("loading");
  const abortRef = useRef<AbortController | null>(null);

  const currentState = stateFromSearchParams(urlSearchParams);

  const runSearch = useCallback((state: SearchState) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setStatus("loading");
    searchJobs(
      {
        q: state.q || undefined,
        workMode: state.workMode,
        employmentType: state.employmentType,
        seniority: state.seniority || undefined,
        company: state.company || undefined,
        locationCountry: state.locationCountry || undefined,
        locationRegion: state.locationRegion || undefined,
        locationCity: state.locationCity || undefined,
        sort: state.sort || undefined,
        limit: DEFAULT_LIMIT,
        offset: state.offset,
      },
      { signal: controller.signal }
    )
      .then((result) => {
        setResponse(result);
        setStatus(result.results.length === 0 ? "empty" : "loaded");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return; // superseded by a newer request -- not a failure
        }
        setStatus("error");
      });
  }, []);

  // Fetch whenever the URL's search state changes (covers initial load,
  // browser back/forward, and every navigate() call below).
  useEffect(() => {
    runSearch(currentState);
    setForm(currentState);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlSearchParams.toString()]);

  function navigate(next: SearchState) {
    const query = searchParamsFromState(next).toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    navigate({ ...currentState, q: form.q, offset: 0 });
  }

  function handleClearSearch() {
    const next = { ...currentState, q: "", offset: 0 };
    setForm((prev) => ({ ...prev, q: "" }));
    navigate(next);
  }

  function handleClearFilters() {
    navigate({
      ...EMPTY_SEARCH_STATE,
      q: currentState.q,
      sort: currentState.sort,
    });
  }

  function toggleListValue(key: "workMode" | "employmentType", value: string) {
    const current = currentState[key];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    navigate({ ...currentState, [key]: next, offset: 0 });
  }

  function handleTextFilterChange(
    key: "seniority" | "company" | "locationCountry" | "locationRegion" | "locationCity",
    value: string
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleTextFilterCommit(
    key: "seniority" | "company" | "locationCountry" | "locationRegion" | "locationCity"
  ) {
    if (form[key] === currentState[key]) return;
    navigate({ ...currentState, [key]: form[key], offset: 0 });
  }

  function handleSortChange(value: string) {
    navigate({ ...currentState, sort: value, offset: 0 });
  }

  function handlePrevious() {
    navigate({ ...currentState, offset: Math.max(0, currentState.offset - DEFAULT_LIMIT) });
  }

  function handleNext() {
    navigate({ ...currentState, offset: currentState.offset + DEFAULT_LIMIT });
  }

  const isLoading = status === "loading";
  const showingStart = response ? response.offset + 1 : 0;
  const showingEnd = response ? response.offset + response.results.length : 0;

  return (
    <main>
      <h1>Job Search</h1>

      <form onSubmit={handleSubmit} className="search-form">
        <label htmlFor="q">Search</label>
        <input
          id="q"
          name="q"
          type="search"
          placeholder="Search job title, company, or keywords…"
          value={form.q}
          onChange={(e) => setForm((prev) => ({ ...prev, q: e.target.value }))}
        />
        <button type="submit" disabled={isLoading}>
          Search
        </button>
        <button type="button" onClick={handleClearSearch} disabled={isLoading}>
          Clear search
        </button>
      </form>

      <section aria-label="Filters">
        <fieldset>
          <legend>Work mode</legend>
          {WORK_MODE_OPTIONS.map((option) => (
            <label key={option.value}>
              <input
                type="checkbox"
                checked={currentState.workMode.includes(option.value)}
                onChange={() => toggleListValue("workMode", option.value)}
              />
              {option.label}
            </label>
          ))}
        </fieldset>

        <fieldset>
          <legend>Employment type</legend>
          {EMPLOYMENT_TYPE_OPTIONS.map((option) => (
            <label key={option.value}>
              <input
                type="checkbox"
                checked={currentState.employmentType.includes(option.value)}
                onChange={() => toggleListValue("employmentType", option.value)}
              />
              {option.label}
            </label>
          ))}
        </fieldset>

        <div className="filter-field">
          <label htmlFor="seniority">Seniority</label>
          <input
            id="seniority"
            type="text"
            value={form.seniority}
            onChange={(e) => handleTextFilterChange("seniority", e.target.value)}
            onBlur={() => handleTextFilterCommit("seniority")}
          />
        </div>

        <div className="filter-field">
          <label htmlFor="company">Company</label>
          <input
            id="company"
            type="text"
            value={form.company}
            onChange={(e) => handleTextFilterChange("company", e.target.value)}
            onBlur={() => handleTextFilterCommit("company")}
          />
        </div>

        <fieldset>
          <legend>Location</legend>
          <label htmlFor="location_country">Country</label>
          <input
            id="location_country"
            type="text"
            value={form.locationCountry}
            onChange={(e) => handleTextFilterChange("locationCountry", e.target.value)}
            onBlur={() => handleTextFilterCommit("locationCountry")}
          />
          <label htmlFor="location_region">Region</label>
          <input
            id="location_region"
            type="text"
            value={form.locationRegion}
            onChange={(e) => handleTextFilterChange("locationRegion", e.target.value)}
            onBlur={() => handleTextFilterCommit("locationRegion")}
          />
          <label htmlFor="location_city">City</label>
          <input
            id="location_city"
            type="text"
            value={form.locationCity}
            onChange={(e) => handleTextFilterChange("locationCity", e.target.value)}
            onBlur={() => handleTextFilterCommit("locationCity")}
          />
        </fieldset>

        <button
          type="button"
          className="filters-clear"
          onClick={handleClearFilters}
          disabled={isLoading}
        >
          Clear all filters
        </button>
      </section>

      <label htmlFor="sort">Sort</label>
      <select
        id="sort"
        value={currentState.sort}
        onChange={(e) => handleSortChange(e.target.value)}
      >
        {SORT_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>

      <section aria-live="polite" className="results">
        {status === "loading" && <p role="status">Searching…</p>}

        {status === "error" && (
          <div role="alert">
            <p>Something went wrong loading job results.</p>
            <button type="button" onClick={() => runSearch(currentState)}>
              Retry
            </button>
          </div>
        )}

        {status === "empty" &&
          (hasActiveQueryOrFilters(currentState) ? (
            <div>
              <p>No jobs found matching your search.</p>
              <button type="button" onClick={handleClearFilters}>
                Clear filters
              </button>
            </div>
          ) : (
            <p>No jobs are available right now.</p>
          ))}

        {status === "loaded" && response && (
          <>
            <p>
              Showing {showingStart}–{showingEnd}
            </p>
            <ul className="job-list">
              {response.results.map((job) => (
                <JobCard key={job.id} job={job} />
              ))}
            </ul>
          </>
        )}
      </section>

      {response && (
        <nav aria-label="Pagination">
          <button type="button" onClick={handlePrevious} disabled={!response.has_previous || isLoading}>
            Previous
          </button>
          <button type="button" onClick={handleNext} disabled={!response.has_next || isLoading}>
            Next
          </button>
        </nav>
      )}
    </main>
  );
}

export default function HomePage() {
  return (
    <Suspense fallback={<main><h1>Job Search</h1><p role="status">Loading…</p></main>}>
      <SearchPageInner />
    </Suspense>
  );
}
