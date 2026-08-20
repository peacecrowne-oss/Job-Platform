import { getApiBaseUrl } from "@/lib/config";

// Placeholder home page (STORY-013). No product features — search, job
// listings, and auth belong to later Stories.
export default function HomePage() {
  const apiBaseUrl = getApiBaseUrl();

  return (
    <main>
      <h1>Job Platform</h1>
      <p>Frontend application foundation (STORY-013). No product features yet.</p>
      <p>Configured API base URL: {apiBaseUrl}</p>
    </main>
  );
}
