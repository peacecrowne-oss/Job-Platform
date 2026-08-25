import { describe, expect, it } from "vitest";

import {
  EMPTY_SEARCH_STATE,
  hasActiveQueryOrFilters,
  searchParamsFromState,
  stateFromSearchParams,
  type SearchState,
} from "@/lib/searchParams";

describe("stateFromSearchParams", () => {
  it("returns the empty state for an empty URL", () => {
    expect(stateFromSearchParams(new URLSearchParams())).toEqual(EMPTY_SEARCH_STATE);
  });

  it("reads q, seniority, company, and location fields", () => {
    const params = new URLSearchParams(
      "q=engineer&seniority=Senior&company=Acme&location_country=Germany&location_region=Berlin&location_city=Berlin"
    );
    const state = stateFromSearchParams(params);
    expect(state.q).toBe("engineer");
    expect(state.seniority).toBe("Senior");
    expect(state.company).toBe("Acme");
    expect(state.locationCountry).toBe("Germany");
    expect(state.locationRegion).toBe("Berlin");
    expect(state.locationCity).toBe("Berlin");
  });

  it("reads repeated work_mode and employment_type values", () => {
    const params = new URLSearchParams(
      "work_mode=remote&work_mode=hybrid&employment_type=full_time"
    );
    const state = stateFromSearchParams(params);
    expect(state.workMode).toEqual(["remote", "hybrid"]);
    expect(state.employmentType).toEqual(["full_time"]);
  });

  it("reads sort", () => {
    expect(stateFromSearchParams(new URLSearchParams("sort=posting_date")).sort).toBe(
      "posting_date"
    );
  });

  it("reads a valid offset", () => {
    expect(stateFromSearchParams(new URLSearchParams("offset=40")).offset).toBe(40);
  });

  it("falls back to offset 0 for a malformed offset", () => {
    expect(stateFromSearchParams(new URLSearchParams("offset=abc")).offset).toBe(0);
    expect(stateFromSearchParams(new URLSearchParams("offset=-5")).offset).toBe(0);
    expect(stateFromSearchParams(new URLSearchParams("offset=1.5")).offset).toBe(0);
  });
});

describe("searchParamsFromState", () => {
  it("produces an empty query string for the empty state", () => {
    expect(searchParamsFromState(EMPTY_SEARCH_STATE).toString()).toBe("");
  });

  it("round-trips through stateFromSearchParams", () => {
    const state: SearchState = {
      q: "engineer",
      workMode: ["remote", "hybrid"],
      employmentType: ["full_time"],
      seniority: "Senior",
      company: "Acme",
      locationCountry: "Germany",
      locationRegion: "Berlin",
      locationCity: "Berlin",
      sort: "posting_date",
      offset: 40,
    };
    const roundTripped = stateFromSearchParams(searchParamsFromState(state));
    expect(roundTripped).toEqual(state);
  });

  it("omits offset when it is 0", () => {
    const params = searchParamsFromState({ ...EMPTY_SEARCH_STATE, offset: 0 });
    expect(params.has("offset")).toBe(false);
  });

  it("encodes repeated work_mode values as repeated params", () => {
    const params = searchParamsFromState({
      ...EMPTY_SEARCH_STATE,
      workMode: ["remote", "hybrid"],
    });
    expect(params.getAll("work_mode")).toEqual(["remote", "hybrid"]);
  });
});

describe("hasActiveQueryOrFilters", () => {
  it("is false for the empty state", () => {
    expect(hasActiveQueryOrFilters(EMPTY_SEARCH_STATE)).toBe(false);
  });

  it("is false when only sort/offset are set", () => {
    expect(
      hasActiveQueryOrFilters({ ...EMPTY_SEARCH_STATE, sort: "posting_date", offset: 20 })
    ).toBe(false);
  });

  it("is true when q is set", () => {
    expect(hasActiveQueryOrFilters({ ...EMPTY_SEARCH_STATE, q: "engineer" })).toBe(true);
  });

  it("is true when any filter is set", () => {
    expect(hasActiveQueryOrFilters({ ...EMPTY_SEARCH_STATE, workMode: ["remote"] })).toBe(true);
    expect(hasActiveQueryOrFilters({ ...EMPTY_SEARCH_STATE, company: "Acme" })).toBe(true);
    expect(hasActiveQueryOrFilters({ ...EMPTY_SEARCH_STATE, locationCity: "Berlin" })).toBe(true);
  });
});
