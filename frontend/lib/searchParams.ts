/**
 * URL query-string <-> search-state conversion (STORY-035's own technical
 * note: "URL state reflects search/filter/sort/page so results are
 * shareable/bookmarkable"). Pure functions only -- no DOM, no Next.js
 * router dependency -- so they're independently unit-testable.
 */

export interface SearchState {
  q: string;
  workMode: string[];
  employmentType: string[];
  seniority: string;
  company: string;
  locationCountry: string;
  locationRegion: string;
  locationCity: string;
  sort: string;
  offset: number;
}

export const DEFAULT_LIMIT = 20;

export const EMPTY_SEARCH_STATE: SearchState = {
  q: "",
  workMode: [],
  employmentType: [],
  seniority: "",
  company: "",
  locationCountry: "",
  locationRegion: "",
  locationCity: "",
  sort: "",
  offset: 0,
};

/** Reads a SearchState back out of the current URL's query string. Any
 * missing/malformed piece falls back to its EMPTY_SEARCH_STATE default,
 * never throwing on an unexpected URL. */
export function stateFromSearchParams(params: URLSearchParams): SearchState {
  const offsetRaw = params.get("offset");
  const offsetParsed = offsetRaw === null ? NaN : Number(offsetRaw);
  const offset = Number.isInteger(offsetParsed) && offsetParsed >= 0 ? offsetParsed : 0;

  return {
    q: params.get("q") ?? "",
    workMode: params.getAll("work_mode"),
    employmentType: params.getAll("employment_type"),
    seniority: params.get("seniority") ?? "",
    company: params.get("company") ?? "",
    locationCountry: params.get("location_country") ?? "",
    locationRegion: params.get("location_region") ?? "",
    locationCity: params.get("location_city") ?? "",
    sort: params.get("sort") ?? "",
    offset,
  };
}

/** Serializes a SearchState into a URLSearchParams -- empty/default
 * fields are omitted entirely (a clean URL, no `?q=&sort=` noise). */
export function searchParamsFromState(state: SearchState): URLSearchParams {
  const params = new URLSearchParams();

  if (state.q) params.set("q", state.q);
  for (const value of state.workMode) params.append("work_mode", value);
  for (const value of state.employmentType) params.append("employment_type", value);
  if (state.seniority) params.set("seniority", state.seniority);
  if (state.company) params.set("company", state.company);
  if (state.locationCountry) params.set("location_country", state.locationCountry);
  if (state.locationRegion) params.set("location_region", state.locationRegion);
  if (state.locationCity) params.set("location_city", state.locationCity);
  if (state.sort) params.set("sort", state.sort);
  if (state.offset > 0) params.set("offset", String(state.offset));

  return params;
}

/** True if any query/filter is active (used to distinguish the two empty-
 * state messages -- "no jobs match" vs. "nothing available at all"). Sort
 * and offset don't count: they don't narrow the result set. */
export function hasActiveQueryOrFilters(state: SearchState): boolean {
  return (
    state.q !== "" ||
    state.workMode.length > 0 ||
    state.employmentType.length > 0 ||
    state.seniority !== "" ||
    state.company !== "" ||
    state.locationCountry !== "" ||
    state.locationRegion !== "" ||
    state.locationCity !== ""
  );
}
