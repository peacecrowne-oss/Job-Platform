import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JobSearchError, searchJobs } from "@/lib/searchApi";

const ORIGINAL_ENV = process.env.NEXT_PUBLIC_API_BASE_URL;

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000";
});

afterEach(() => {
  if (ORIGINAL_ENV === undefined) {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
  } else {
    process.env.NEXT_PUBLIC_API_BASE_URL = ORIGINAL_ENV;
  }
  vi.restoreAllMocks();
});

function mockFetchOnce(response: Partial<Response>) {
  const fetchMock = vi.fn().mockResolvedValue(response as Response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("searchJobs", () => {
  it("requests the correct base path", async () => {
    const fetchMock = mockFetchOnce({
      ok: true,
      json: async () => ({ query: null, limit: 20, offset: 0, has_next: false, has_previous: false, results: [] }),
    });

    await searchJobs({});

    const requestedUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(requestedUrl.origin + requestedUrl.pathname).toBe("http://localhost:8000/jobs/search");
  });

  it("encodes q, limit, and offset", async () => {
    const fetchMock = mockFetchOnce({
      ok: true,
      json: async () => ({ query: "engineer", limit: 20, offset: 40, has_next: false, has_previous: true, results: [] }),
    });

    await searchJobs({ q: "engineer", limit: 20, offset: 40 });

    const requestedUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(requestedUrl.searchParams.get("q")).toBe("engineer");
    expect(requestedUrl.searchParams.get("limit")).toBe("20");
    expect(requestedUrl.searchParams.get("offset")).toBe("40");
  });

  it("encodes special characters in q safely", async () => {
    const fetchMock = mockFetchOnce({
      ok: true,
      json: async () => ({ query: null, limit: 20, offset: 0, has_next: false, has_previous: false, results: [] }),
    });

    await searchJobs({ q: "C++ & R&D / \"quoted\"" });

    const requestedUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(requestedUrl.searchParams.get("q")).toBe('C++ & R&D / "quoted"');
  });

  it("encodes repeated work_mode and employment_type values", async () => {
    const fetchMock = mockFetchOnce({
      ok: true,
      json: async () => ({ query: null, limit: 20, offset: 0, has_next: false, has_previous: false, results: [] }),
    });

    await searchJobs({ workMode: ["remote", "hybrid"], employmentType: ["full_time"] });

    const requestedUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(requestedUrl.searchParams.getAll("work_mode")).toEqual(["remote", "hybrid"]);
    expect(requestedUrl.searchParams.getAll("employment_type")).toEqual(["full_time"]);
  });

  it("omits unset optional params entirely", async () => {
    const fetchMock = mockFetchOnce({
      ok: true,
      json: async () => ({ query: null, limit: 20, offset: 0, has_next: false, has_previous: false, results: [] }),
    });

    await searchJobs({});

    const requestedUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(requestedUrl.searchParams.has("q")).toBe(false);
    expect(requestedUrl.searchParams.has("sort")).toBe(false);
    expect(requestedUrl.searchParams.has("company")).toBe(false);
  });

  it("returns the parsed response on success", async () => {
    const payload = {
      query: "engineer",
      limit: 20,
      offset: 0,
      has_next: false,
      has_previous: false,
      results: [],
    };
    mockFetchOnce({ ok: true, json: async () => payload });

    const result = await searchJobs({ q: "engineer" });

    expect(result).toEqual(payload);
  });

  it("throws JobSearchError with a generic message on a non-2xx response", async () => {
    mockFetchOnce({ ok: false, status: 500, json: async () => ({ error: { message: "internal" } }) });

    await expect(searchJobs({})).rejects.toBeInstanceOf(JobSearchError);
    await expect(searchJobs({})).rejects.not.toThrow(/internal/);
  });

  it("propagates a network failure as a rejected promise", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(searchJobs({})).rejects.toThrow();
  });

  it("passes the abort signal through to fetch", async () => {
    const fetchMock = mockFetchOnce({
      ok: true,
      json: async () => ({ query: null, limit: 20, offset: 0, has_next: false, has_previous: false, results: [] }),
    });
    const controller = new AbortController();

    await searchJobs({}, { signal: controller.signal });

    expect(fetchMock.mock.calls[0][1]).toMatchObject({ signal: controller.signal });
  });
});
