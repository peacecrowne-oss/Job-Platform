import type { NextConfig } from "next";
import { existsSync } from "node:fs";
import path from "node:path";

// The repository uses a single root-level `.env` (see `.env.example` /
// STORY-006) shared by backend and frontend, rather than a frontend-local
// one. Next.js only auto-loads `.env*` files from its own project
// directory, so load the root `.env` explicitly here. Variables already
// present in the environment (e.g. set by Docker later) are not overridden.
const rootEnvPath = path.resolve(process.cwd(), "..", ".env");
if (existsSync(rootEnvPath)) {
  process.loadEnvFile(rootEnvPath);
}

const nextConfig: NextConfig = {
  // Bundles a minimal server + only the node_modules actually needed,
  // instead of shipping the full node_modules tree in the runtime image
  // (STORY-004's "keep images small" requirement).
  output: "standalone",
};

export default nextConfig;
