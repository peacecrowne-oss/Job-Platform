function normalizeBaseUrl(value: string, varName: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${varName} is not a valid URL: "${value}". Check your .env file.`);
  }
  return parsed.toString().replace(/\/$/, "");
}

/**
 * Environment-driven API base URL (STORY-013).
 *
 * A missing or malformed value must fail visibly at render time, not fall
 * back to a silent default, per STORY-013's edge-case requirement.
 */
export function getApiBaseUrl(): string {
  const value = process.env.NEXT_PUBLIC_API_BASE_URL;

  if (!value || value.trim() === "") {
    throw new Error(
      "NEXT_PUBLIC_API_BASE_URL is not set. Copy .env.example to .env at the " +
        "repository root and set it before starting the frontend — see README.md."
    );
  }

  return normalizeBaseUrl(value, "NEXT_PUBLIC_API_BASE_URL");
}

/**
 * Server-side-only API base URL (STORY-034) -- for use only inside a
 * Server Component/route handler, never in client-side code. Docker
 * Compose runs the frontend and backend as separate containers where
 * "localhost" means "this container," not the backend -- a plain
 * NEXT_PUBLIC_API_BASE_URL of "http://localhost:8000" (correct for a
 * browser) is unreachable from the Next.js server process itself.
 * INTERNAL_API_BASE_URL (e.g. "http://backend:8000", the Compose service
 * name) is for exactly that case; falls back to
 * NEXT_PUBLIC_API_BASE_URL when unset, matching a non-Docker local setup
 * where both processes really do share one "localhost".
 */
export function getServerApiBaseUrl(): string {
  const value = process.env.INTERNAL_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;

  if (!value || value.trim() === "") {
    throw new Error(
      "Neither INTERNAL_API_BASE_URL nor NEXT_PUBLIC_API_BASE_URL is set. Copy " +
        ".env.example to .env at the repository root and set one before starting " +
        "the frontend — see README.md."
    );
  }

  return normalizeBaseUrl(
    value,
    process.env.INTERNAL_API_BASE_URL ? "INTERNAL_API_BASE_URL" : "NEXT_PUBLIC_API_BASE_URL"
  );
}
