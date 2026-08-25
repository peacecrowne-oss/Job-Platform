import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Unmounts every rendered component after each test -- without this,
// consecutive tests in the same file accumulate DOM from prior renders,
// breaking getByText()/queryByText() queries that expect a single match.
afterEach(() => {
  cleanup();
});
