/** Only http/https links are ever rendered as clickable -- a defensive
 * guard against a hypothetical malformed source_url/application_url (e.g.
 * a javascript: URI), even though no current connector would produce one.
 * Extracted from JobCard.tsx (STORY-035) when the job detail page
 * (STORY-034) needed the exact same check -- a security-relevant check
 * should have one implementation, not two copies that could drift. */
export function isSafeHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}
