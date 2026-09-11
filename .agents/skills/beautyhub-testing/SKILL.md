---
name: beautyhub-testing
description: Plan, implement, review, or report BeautyHub verification across pytest unit tests, PostgreSQL integration and concurrency, API contracts and security, Playwright journeys, Axe, and manual release checks. Use for an approved testing task; do not use coverage metrics to redefine completion.
license: MIT
---

# BeautyHub Testing

Create direct, traceable evidence for the active spec and task.

## Workflow

1. Read `AGENTS.md`, `docs/constitution.md`, the active spec, approved plan, and selected task.
2. Extract the exact RF/EARS/RNF identifiers in scope and identify the lowest test layer that can prove each behavior.
3. Use unit tests for pure rules, PostgreSQL integration tests for database invariants and races, contract/security tests for HTTP boundaries, and Playwright for rendered user journeys. A critical rule must not rely only on E2E evidence.
4. Use fictitious data and controlled clocks, entropy, and provider doubles. Never place personal data or secrets in fixtures, test names, output, screenshots, traces, or committed reports.
5. Run only project commands that exist and are authorized. Do not install a test plugin, browser, service, or alternative package manager without explicit approval.
6. Report commands, pass/fail results, uncovered criteria, and residual environment/device risk. Never call a skipped or unexecuted check successful.

Read [references/backend-testing.md](references/backend-testing.md) for pytest, PostgreSQL, contract, security, and concurrency work. Read [references/frontend-e2e.md](references/frontend-e2e.md) for Playwright, Axe, responsive, and manual evidence. Read [references/traceability.md](references/traceability.md) when planning or auditing RF/EARS coverage. Read [references/sources.md](references/sources.md) for provenance and excluded upstream rules.
