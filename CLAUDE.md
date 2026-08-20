# Human Approval and Execution Policy

This policy applies to **every Claude Code session and every project ticket**.

## Mandatory Human Approval

Claude must use the following workflow:

1. Read `requirement.md`.
2. Read `progress.md`.
3. Inspect the relevant repository state.
4. Determine the proposed work.
5. Present the proposed plan to the human.
6. **STOP and request explicit human approval before modifying implementation files.**
7. Only after explicit approval, perform the approved work.
8. Run applicable validation.
9. Update `progress.md`.
10. Present a completion summary.
11. **STOP and wait for human approval before beginning additional work.**

Human approval is required between tickets and implementation phases.

## What Claude May Do Before Approval

Before approval, Claude may perform read-only activities necessary to understand the project, including:

* read `requirement.md`;
* read `progress.md`;
* inspect repository files;
* inspect directory structure;
* inspect Git status/diff/history;
* inspect existing tests;
* inspect configuration;
* analyze dependencies;
* identify blockers;
* determine applicable tests;
* prepare an implementation plan.

Claude must not make implementation changes during this phase.

## Approval Request Format

Before implementation, Claude must provide:

### Proposed Work

**Ticket(s):**

* STORY-NNN — Story Title

**Current status:**
Brief description of what currently exists.

**Planned changes:**

* files to create;
* files to modify;
* implementation behavior;
* tests to add/update;
* documentation/progress updates.

**Validation planned:**

* commands/tests that will be run.

**Risks / assumptions:**

* relevant implementation assumptions;
* potential risks;
* dependencies or blockers.

**Estimated scope:**
Small / Medium / Large.

Then Claude must ask:

**Approve this implementation plan? (yes/no)**

Claude must stop and wait for the answer.

## Approval Interpretation

Explicit approvals include responses such as:

* `yes`
* `approved`
* `proceed`
* `go ahead`
* `implement it`

A request to change the plan is **not** approval.

If the human changes scope, Claude must revise the plan and request approval again before implementation.

Approval applies only to the work described in the approved plan.

Claude must not treat approval for one Story as authorization to implement subsequent Stories.

## Scope Control

During implementation, Claude must remain within the approved scope.

If Claude discovers that a material additional change is necessary:

1. stop before making that additional change;
2. explain what was discovered;
3. explain the proposed additional work;
4. request human approval.

Minor implementation details that are clearly necessary to complete the approved Story do not require a second approval, provided they do not materially expand scope.

## Destructive or High-Impact Operations

Claude must obtain explicit approval before operations such as:

* deleting significant files or directories;
* destructive database migrations;
* resetting databases;
* deleting data;
* force Git operations;
* rewriting Git history;
* modifying deployment infrastructure;
* deploying;
* changing production configuration;
* rotating or modifying credentials;
* performing remote Git operations;
* introducing a major new dependency or architecture outside the approved plan.

Never assume authorization for these operations.

## Validation

After implementation, Claude must run all validation applicable to the approved work.

Where applicable this includes:

* unit tests;
* integration tests;
* linting;
* formatting checks;
* type checking;
* build validation;
* migration validation;
* Docker configuration validation;
* security/configuration checks.

Claude must distinguish:

* checks actually executed;
* checks that passed;
* checks that failed;
* checks that could not be run.

Never report a check as passing unless it was actually executed successfully.

## progress.md

After an approved implementation run, update `progress.md` with:

* Story ID;
* Story title;
* status;
* completion percentage;
* files created;
* files modified;
* implementation summary;
* tests/checks executed;
* actual results;
* decisions;
* assumptions;
* blockers;
* next recommended Story.

A Story may only be marked **100% Complete** when its acceptance criteria have been verified and its required validation passes.

Do not mark a Story complete merely because code exists.

## Mandatory Completion Summary

Every implementation run must end with:

### Run Summary

**Ticket(s):**

* STORY-NNN — Title

**Status:** Complete / Partial / Blocked / Failed

**Completion:** NN%

**Changes made:**

* concise description

**Files created:**

* file paths or `None`

**Files modified:**

* file paths or `None`

**Validation:**

| Check         | Result                |
| ------------- | --------------------- |
| command/check | PASS / FAIL / NOT RUN |

**Acceptance criteria:**

* Passed: X
* Failed: X
* Remaining: X

**Issues / blockers:**

* issue or `None`

**progress.md updated:** Yes/No

**Recommended next ticket:**

* STORY-NNN — Title

**Next action requires human approval:** Yes

Claude must then stop.

## No Automatic Continuation

Claude must never automatically move from:

`STORY-A → STORY-B`

just because STORY-A completed successfully.

Instead:

`inspect → propose → human approval → implement → validate → summarize → stop`

The human decides whether Claude proceeds to the next ticket.

## Source of Truth

Story IDs currently defined in `requirement.md` are authoritative.

Execution order comes from:

1. dependencies;
2. priority;
3. `Implementation Sequence for Claude`;
4. current repository state;
5. blockers.

Story number alone does not determine implementation order.

Claude must continue preserving the historical Story-ID mismatch documented in `progress.md` unless the human explicitly approves its cleanup.
