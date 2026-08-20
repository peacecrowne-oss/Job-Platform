# syntax=docker/dockerfile:1

# --- deps stage: install dependencies reproducibly from the lockfile ---
FROM node:22.11.0-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# --- build stage: requires NEXT_PUBLIC_API_BASE_URL; the app's own
#     lib/config.ts throws a clear error and fails the build if it's
#     missing or not a valid URL (see STORY-013) ---
FROM node:22.11.0-bookworm-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
RUN npm run build

# --- runtime stage: minimal Next.js standalone server, non-root user ---
FROM node:22.11.0-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production

RUN useradd --create-home --shell /usr/sbin/nologin appuser

# No public/ directory exists yet (placeholder page has no static assets);
# add `COPY --from=build --chown=appuser:appuser /app/public ./public` here
# once one does.
COPY --from=build --chown=appuser:appuser /app/.next/standalone ./
COPY --from=build --chown=appuser:appuser /app/.next/static ./.next/static

USER appuser
EXPOSE 3000
ENV PORT=3000
# Docker auto-injects HOSTNAME=<container id> into every container's
# environment, and the Next.js standalone server binds to
# `process.env.HOSTNAME || '0.0.0.0'` — since HOSTNAME is always truthy here,
# it would otherwise bind only to the container's own hostname/interface
# instead of all interfaces, making the app unreachable via loopback
# (breaks in-container healthchecks) even though host port-publishing still
# happens to work. Overriding it here forces the intended bind-all behavior.
ENV HOSTNAME="0.0.0.0"
CMD ["node", "server.js"]
