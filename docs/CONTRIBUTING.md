# Contributing / Git Conventions

This document implements **STORY-002 — Git Conventions** from
[`requirement.md`](../requirement.md). It is referenced from the top-level
[`README.md`](../README.md).

## Branching

- Trunk-based development on `main`.
- Work happens on short-lived feature branches, prefixed by change type:
  - `feat/` — new functionality
  - `fix/` — bug fixes
  - `chore/` — tooling, dependencies, non-functional maintenance
  - `docs/` — documentation-only changes
- Example: `feat/greenhouse-connector`, `fix/dedup-null-source-id`.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) style:

```
type(scope): summary

optional longer body explaining why, not just what
```

Common `type` values: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`.
`scope` is optional and should name the affected area (e.g. `backend`, `frontend`,
`connectors`, `ci`).

## Pull requests

- PRs are required to merge into `main` once there is more than one collaborator on
  the repository.
- **Solo-maintainer period**: while the repository has a single maintainer, direct
  commits to `main` are permitted. This relaxation is explicit, not an oversight —
  it ends as soon as a second collaborator joins the project, at which point the PR
  requirement above applies without exception.

## `.gitignore`

The repository-root [`.gitignore`](../.gitignore) covers, at minimum:

- Python build/cache artifacts (backend)
- Node/Next.js build and dependency artifacts (frontend)
- environment files (`.env`, `.env.*`), while explicitly keeping `.env.example`
  tracked
- test artifacts (coverage reports, Playwright output)
- IDE/editor files
- logs
- OS metadata files
- local database files

No real secrets, credentials, or populated `.env` files are ever committed. Only
`.env.example`, containing variable names and safe placeholder values, is tracked
(see **STORY-006** and [`.env.example`](../.env.example)).
