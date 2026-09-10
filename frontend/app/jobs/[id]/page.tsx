import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { getJob, type JobDetail } from "@/lib/jobApi";
import { EMPLOYMENT_TYPE_LABELS, WORK_MODE_LABELS } from "@/lib/labels";
import { isSafeHttpUrl } from "@/lib/urlSafety";

/** Async Server Component -- genuinely server-rendered (not just labeled
 * as such), per STORY-034's own "server-rendered for SEO where feasible"
 * technical note. `notFound()` (next/navigation) gives a real HTTP 404 for
 * a nonexistent job, distinct from the inline error state below (a fetch/
 * network failure, not "this job doesn't exist"). */

type PageParams = { params: Promise<{ id: string }> };

function formatDate(value: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function locationLine(job: JobDetail): string | null {
  const parts = [job.location_city, job.location_region, job.location_country].filter(
    (part): part is string => Boolean(part)
  );
  return parts.length > 0 ? parts.join(", ") : null;
}

function compensationLine(job: JobDetail): string | null {
  const { compensation_min: min, compensation_max: max, compensation_currency: currency, compensation_period: period } =
    job;
  if (!min && !max) return null;

  const fmt = (value: string) => Number(value).toLocaleString();
  let range: string;
  if (min && max) range = `${fmt(min)}–${fmt(max)}`;
  else if (min) range = `${fmt(min)}+`;
  else range = `Up to ${fmt(max as string)}`;

  const withCurrency = currency ? `${range} ${currency}` : range;
  return period ? `${withCurrency} / ${period}` : withCurrency;
}

export async function generateMetadata({ params }: PageParams): Promise<Metadata> {
  const { id } = await params;
  const job = await getJob(id);
  if (!job) return { title: "Job not found" };
  const title = job.company_name ? `${job.job_title ?? "Untitled role"} at ${job.company_name}` : job.job_title ?? "Job";
  return { title };
}

export default async function JobDetailPage({ params }: PageParams) {
  const { id } = await params;

  let job: JobDetail | null;
  try {
    job = await getJob(id);
  } catch {
    return (
      <main>
        <p role="alert">Something went wrong loading this job.</p>
        <Link href="/">Back to search</Link>
      </main>
    );
  }

  if (!job) {
    notFound();
  }

  const location = locationLine(job);
  const workModeLabel = job.work_mode ? WORK_MODE_LABELS[job.work_mode] ?? job.work_mode : null;
  const employmentTypeLabel = job.employment_type
    ? EMPLOYMENT_TYPE_LABELS[job.employment_type] ?? job.employment_type
    : null;
  const postingDate = formatDate(job.posting_date);
  const closingDate = formatDate(job.closing_date);
  const lastSeenDate = formatDate(job.last_seen_at);
  const compensation = compensationLine(job);
  const isClosed = job.closed_at !== null;

  return (
    <main className="job-detail">
      <Link href="/">&larr; Back to search</Link>

      <h1>{job.job_title ?? "Untitled role"}</h1>
      {isClosed && (
        <p role="status" className="job-detail__closed-badge">
          Closed
        </p>
      )}
      {job.company_name && <p className="job-card__company">{job.company_name}</p>}
      {location && <p className="job-card__location">{location}</p>}

      {(workModeLabel || employmentTypeLabel || job.seniority || job.department) && (
        <ul className="job-card__tags">
          {workModeLabel && <li className="job-card__tag">{workModeLabel}</li>}
          {employmentTypeLabel && <li className="job-card__tag">{employmentTypeLabel}</li>}
          {job.seniority && <li className="job-card__tag">{job.seniority}</li>}
          {job.department && <li className="job-card__tag">{job.department}</li>}
        </ul>
      )}

      <p className="job-card__links">
        {job.application_url && isSafeHttpUrl(job.application_url) && (
          <a href={job.application_url} target="_blank" rel="noopener noreferrer">
            Apply&nbsp;<span aria-hidden="true">&#8599;</span>
          </a>
        )}
        {job.source_url && isSafeHttpUrl(job.source_url) && (
          <a href={job.source_url} target="_blank" rel="noopener noreferrer">
            View original posting&nbsp;<span aria-hidden="true">&#8599;</span>
          </a>
        )}
      </p>

      {job.description_full && (
        <section aria-label="Description">
          <h2>Description</h2>
          {/* Security boundary: description_full has passed through
              sanitize_html() twice server-side (ingest, STORY-047; and
              again in GET /jobs/{id}, STORY-034) before reaching this
              client -- the only reason dangerouslySetInnerHTML is safe
              here. Never apply this pattern to any other field. */}
          <div dangerouslySetInnerHTML={{ __html: job.description_full }} />
        </section>
      )}

      {job.responsibilities && (
        <section aria-label="Responsibilities">
          <h2>Responsibilities</h2>
          <div dangerouslySetInnerHTML={{ __html: job.responsibilities }} />
        </section>
      )}

      {job.requirements && (
        <section aria-label="Requirements">
          <h2>Requirements</h2>
          <div dangerouslySetInnerHTML={{ __html: job.requirements }} />
        </section>
      )}

      {job.preferred_requirements && (
        <section aria-label="Preferred Requirements">
          <h2>Preferred Requirements</h2>
          <div dangerouslySetInnerHTML={{ __html: job.preferred_requirements }} />
        </section>
      )}

      {job.qualifications && (
        <section aria-label="Qualifications">
          <h2>Qualifications</h2>
          <div dangerouslySetInnerHTML={{ __html: job.qualifications }} />
        </section>
      )}

      {job.skills && job.skills.length > 0 && (
        <section aria-label="Skills">
          <h2>Skills</h2>
          <ul className="job-card__tags">
            {job.skills.map((skill) => (
              <li key={skill} className="job-card__tag">
                {skill}
              </li>
            ))}
          </ul>
        </section>
      )}

      {compensation && (
        <section aria-label="Compensation">
          <h2>Compensation</h2>
          <p>{compensation}</p>
        </section>
      )}

      {job.benefits && job.benefits.length > 0 && (
        <section aria-label="Benefits">
          <h2>Benefits</h2>
          <ul>
            {job.benefits.map((benefit) => (
              <li key={benefit}>{benefit}</li>
            ))}
          </ul>
        </section>
      )}

      {(postingDate || closingDate) && (
        <section aria-label="Dates">
          {postingDate && <p>Posted {postingDate}</p>}
          {closingDate && <p>Closes {closingDate}</p>}
        </section>
      )}

      <section aria-label="Source">
        <h2>Source</h2>
        <p>{job.source}</p>
        {lastSeenDate && <p className="job-card__date">Last confirmed active {lastSeenDate}</p>}
      </section>
    </main>
  );
}
