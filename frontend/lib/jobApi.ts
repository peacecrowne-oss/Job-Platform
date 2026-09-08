import { getServerApiBaseUrl } from "@/lib/config";

/**
 * Typed client for `GET /jobs/{id}` (STORY-034), called only from the
 * job detail Server Component -- uses `getServerApiBaseUrl()`
 * (server-side-only), not `getApiBaseUrl()` (browser-facing, used by
 * `searchApi.ts`). Types mirror the backend's real Pydantic response
 * schema (app/api/jobs.py) exactly.
 *
 * Security boundary: `description_full`/`responsibilities`/`requirements`/
 * `preferred_requirements`/`qualifications` have already passed through
 * `sanitize_html()` twice server-side (ingest time, STORY-047, and again
 * in this endpoint) by the time they reach this client. Only these five
 * fields may ever be passed to `dangerouslySetInnerHTML` -- never any
 * other value, and never anything from an untrusted client-side source.
 */

export interface JobDetail {
  id: string;
  source: string;
  source_url: string | null;
  source_job_id: string;
  company_name: string | null;
  job_title: string | null;
  description_full: string | null;
  responsibilities: string | null;
  requirements: string | null;
  preferred_requirements: string | null;
  qualifications: string | null;
  skills: string[] | null;
  location_city: string | null;
  location_region: string | null;
  location_country: string | null;
  work_mode: string | null;
  employment_type: string | null;
  seniority: string | null;
  department: string | null;
  compensation_min: string | null;
  compensation_max: string | null;
  compensation_currency: string | null;
  compensation_period: string | null;
  benefits: string[] | null;
  posting_date: string | null;
  closing_date: string | null;
  application_url: string | null;
  first_seen_at: string;
  last_seen_at: string;
  source_updated_at: string | null;
  closed_at: string | null;
}

export class JobDetailError extends Error {
  readonly notFound: boolean;

  constructor(message: string, options?: { notFound?: boolean }) {
    super(message);
    this.name = "JobDetailError";
    this.notFound = options?.notFound ?? false;
  }
}

/** Fetches one job's full detail from the real backend. Returns `null`
 * for a 404 (not found) rather than throwing, since that's an expected,
 * routine outcome for the caller to render a "not found" state around;
 * any other non-2xx status throws. */
export async function getJob(id: string): Promise<JobDetail | null> {
  const url = new URL(`/jobs/${encodeURIComponent(id)}`, getServerApiBaseUrl());
  const response = await fetch(url.toString());

  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new JobDetailError(`Job detail request failed with status ${response.status}.`);
  }

  return (await response.json()) as JobDetail;
}
