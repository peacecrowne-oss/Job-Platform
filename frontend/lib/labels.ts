/** Shared display labels for controlled-value job fields. Extracted from
 * JobCard.tsx (STORY-035) when the job detail page (STORY-034) needed the
 * exact same lookups -- one source of truth for how a value is labeled. */

export const WORK_MODE_LABELS: Record<string, string> = {
  remote: "Remote",
  hybrid: "Hybrid",
  on_site: "On-site",
};

export const EMPLOYMENT_TYPE_LABELS: Record<string, string> = {
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  temporary: "Temporary",
  internship: "Internship",
  apprenticeship: "Apprenticeship",
  other: "Other",
};
