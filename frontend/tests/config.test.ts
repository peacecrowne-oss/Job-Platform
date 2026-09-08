import { afterEach, describe, expect, it } from "vitest";
import { getApiBaseUrl, getServerApiBaseUrl } from "../lib/config";

const ORIGINAL_ENV = process.env.NEXT_PUBLIC_API_BASE_URL;
const ORIGINAL_INTERNAL_ENV = process.env.INTERNAL_API_BASE_URL;

afterEach(() => {
  if (ORIGINAL_ENV === undefined) {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
  } else {
    process.env.NEXT_PUBLIC_API_BASE_URL = ORIGINAL_ENV;
  }
  if (ORIGINAL_INTERNAL_ENV === undefined) {
    delete process.env.INTERNAL_API_BASE_URL;
  } else {
    process.env.INTERNAL_API_BASE_URL = ORIGINAL_INTERNAL_ENV;
  }
});

describe("getApiBaseUrl", () => {
  it("returns the configured URL", () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000";

    expect(getApiBaseUrl()).toBe("http://localhost:8000");
  });

  it("throws visibly when the variable is missing", () => {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;

    expect(() => getApiBaseUrl()).toThrow(/NEXT_PUBLIC_API_BASE_URL is not set/);
  });

  it("throws visibly when the variable is blank", () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "   ";

    expect(() => getApiBaseUrl()).toThrow(/NEXT_PUBLIC_API_BASE_URL is not set/);
  });

  it("throws visibly when the variable is not a valid URL", () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "not-a-url";

    expect(() => getApiBaseUrl()).toThrow(/not a valid URL/);
  });
});

describe("getServerApiBaseUrl", () => {
  it("prefers INTERNAL_API_BASE_URL when set", () => {
    process.env.INTERNAL_API_BASE_URL = "http://backend:8000";
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000";

    expect(getServerApiBaseUrl()).toBe("http://backend:8000");
  });

  it("falls back to NEXT_PUBLIC_API_BASE_URL when INTERNAL_API_BASE_URL is unset", () => {
    delete process.env.INTERNAL_API_BASE_URL;
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000";

    expect(getServerApiBaseUrl()).toBe("http://localhost:8000");
  });

  it("throws visibly when neither variable is set", () => {
    delete process.env.INTERNAL_API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;

    expect(() => getServerApiBaseUrl()).toThrow(/INTERNAL_API_BASE_URL/);
  });

  it("throws visibly when INTERNAL_API_BASE_URL is set but not a valid URL", () => {
    process.env.INTERNAL_API_BASE_URL = "not-a-url";

    expect(() => getServerApiBaseUrl()).toThrow(/INTERNAL_API_BASE_URL is not a valid URL/);
  });
});
