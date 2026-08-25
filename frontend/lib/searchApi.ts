import { getApiBaseUrl } from "@/lib/config";

/**
 * Typed client for `GET /jobs/search` (STORY-030/031/032/033). Types below
 * mirror the backend's real Pydantic response schema (app/api/search.py)
 * exactly -- no field is invented, none of the fields the backend omits
 * (compensation, description, total count) appear here either.
 */

export type WorkMode = "remote" | "hybrid" | "on_site";

export type EmploymentType =
  | "full_time"
  | "part_time"
  | "contract"
  | "temporary"
  | "internship"
  | "apprenticeship"
  | "other";

export type SortMode = "relevance" | "posting_date" | "last_seen";

export interface JobSearchResult {
  id: string;
  source: string;
  job_title: string | null;
  company_name: string | null;
  location_city: string | null;
  location_region: string | null;
  location_country: string | null;
  work_mode: string | null;
  employment_type: string | null;
  seniority: string | null;
  department: string | null;
  posting_date: string | null;
  source_url: string | null;
  application_url: string | null;
}

export interface JobSearchResponse {
  query: string | null;
  limit: number;
  offset: number;
  has_next: boolean;
  has_previous: boolean;
  results: JobSearchResult[];
}

export interface JobSearchParams {
  q?: string;
  workMode?: string[];
  employmentType?: string[];
  seniority?: string;
  company?: string;
  locationCountry?: string;
  locationRegion?: string;
  locationCity?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

export class JobSearchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "JobSearchError";
  }
}

function buildSearchUrl(params: JobSearchParams): string {
  const url = new URL("/jobs/search", getApiBaseUrl());
  const sp = url.searchParams;

  if (params.q) sp.set("q", params.q);
  if (params.seniority) sp.set("seniority", params.seniority);
  if (params.company) sp.set("company", params.company);
  if (params.locationCountry) sp.set("location_country", params.locationCountry);
  if (params.locationRegion) sp.set("location_region", params.locationRegion);
  if (params.locationCity) sp.set("location_city", params.locationCity);
  if (params.sort) sp.set("sort", params.sort);
  if (params.limit !== undefined) sp.set("limit", String(params.limit));
  if (params.offset !== undefined) sp.set("offset", String(params.offset));

  // Repeatable backend params -- each value as its own query-string
  // occurrence, matching FastAPI's list[...] parsing exactly.
  for (const value of params.workMode ?? []) sp.append("work_mode", value);
  for (const value of params.employmentType ?? []) sp.append("employment_type", value);

  return url.toString();
}

/**
 * Fetches one page of search results from the real backend. Never throws
 * the backend's raw error payload -- a generic, safe message only. Pass
 * `signal` to cancel a stale request when a newer one supersedes it; an
 * aborted request rejects with `DOMException` (name "AbortError"), which
 * callers should treat as "cancelled," not "failed."
 */
export async function searchJobs(
  params: JobSearchParams,
  options?: { signal?: AbortSignal }
): Promise<JobSearchResponse> {
  const response = await fetch(buildSearchUrl(params), { signal: options?.signal });

  if (!response.ok) {
    throw new JobSearchError(
      `Job search request failed with status ${response.status}.`
    );
  }

  return (await response.json()) as JobSearchResponse;
}
