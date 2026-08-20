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

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(
      `NEXT_PUBLIC_API_BASE_URL is not a valid URL: "${value}". Check your .env file.`
    );
  }

  return parsed.toString().replace(/\/$/, "");
}
