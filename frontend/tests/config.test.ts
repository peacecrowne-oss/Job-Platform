import { afterEach, describe, expect, it } from "vitest";
import { getApiBaseUrl } from "../lib/config";

const ORIGINAL_ENV = process.env.NEXT_PUBLIC_API_BASE_URL;

afterEach(() => {
  if (ORIGINAL_ENV === undefined) {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
  } else {
    process.env.NEXT_PUBLIC_API_BASE_URL = ORIGINAL_ENV;
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
