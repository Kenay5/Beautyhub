# RF/EARS traceability

## Building the map

- Derive identifiers from the current approved spec rather than copying an old count.
- For each EARS criterion, record the proving test ID or planned test, layer, task, and relevant boundary/data variation.
- Map RNFs and release gates separately from functional criteria; do not hide them under a generic RF row.
- Flag a criterion as uncovered when no test directly observes its required result. Shared setup or a neighboring RF is not coverage.
- Flag tests with no approved RF/RNF, bug reproduction, or technical plan invariant; they may be unanchored scope.

## Choosing the layer

- Pure validation, state, time, ordering, and permission decisions: unit test first.
- PostgreSQL constraints, migrations, locking, idempotency, retention, and races: integration test.
- HTTP schema, authorization, sanitization, cookies, CSRF, limits, and provider result translation: contract/security test.
- Complete visible journeys, browser behavior, responsive design, and accessibility automation: Playwright.
- Real providers, devices, restoration, backups, and publication checks: controlled operational/manual evidence where the plan requires it.

One test may prove multiple criteria when each assertion is direct and readable. Do not duplicate tests solely to produce one test per row.

## Coverage report

Report exact counts for criteria in scope, mapped, executed, passing, failing, blocked, and not applicable. Keep these states distinct. Line or branch coverage may help locate weak areas, but no percentage substitutes for RF/EARS traceability or the constitution's completion rules.
