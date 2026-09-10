import Link from "next/link";

import { EMPLOYMENT_TYPE_LABELS, WORK_MODE_LABELS } from "@/lib/labels";
import type { JobSearchResult } from "@/lib/searchApi";
import { isSafeHttpUrl } from "@/lib/urlSafety";

function formatPostingDate(value: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function locationLine(job: JobSearchResult): string | null {
  const parts = [job.location_city, job.location_region, job.location_country].filter(
    (part): part is string => Boolean(part)
  );
  return parts.length > 0 ? parts.join(", ") : null;
}

export function JobCard({ job }: { job: JobSearchResult }) {
  const location = locationLine(job);
  const postingDate = formatPostingDate(job.posting_date);
  const workModeLabel = job.work_mode ? WORK_MODE_LABELS[job.work_mode] ?? job.work_mode : null;
  const employmentTypeLabel = job.employment_type
    ? EMPLOYMENT_TYPE_LABELS[job.employment_type] ?? job.employment_type
    : null;

  return (
    <li className="job-card">
      <h3 className="job-card__title">
        <Link href={`/jobs/${job.id}`}>{job.job_title ?? "Untitled role"}</Link>
      </h3>
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

      {postingDate && <p className="job-card__date">Posted {postingDate}</p>}

      <p className="job-card__links">
        {job.source_url && isSafeHttpUrl(job.source_url) && (
          <a href={job.source_url} target="_blank" rel="noopener noreferrer">
            View original posting&nbsp;<span aria-hidden="true">↗</span>
          </a>
        )}
        {job.application_url && isSafeHttpUrl(job.application_url) && (
          <a href={job.application_url} target="_blank" rel="noopener noreferrer">
            Apply&nbsp;<span aria-hidden="true">↗</span>
          </a>
        )}
      </p>
    </li>
  );
}
