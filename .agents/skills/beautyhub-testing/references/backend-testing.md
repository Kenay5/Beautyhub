# Backend testing

## Pytest structure

- Mirror the source boundary using the approved `unit`, `integration`, and `contract` suites.
- Name tests for observable behavior and boundary conditions, not internal method calls.
- Keep fixtures at the narrowest useful scope. Prefer small factory fixtures over inheritance or mutable session-scoped state.
- Use parametrization with readable IDs for equivalence classes and exact neighboring boundaries.
- Use plain assertions and specific expected exceptions or domain outcomes. Do not assert incidental implementation details.
- Ensure each test runs independently and leaves its database or external double in a known state.

## Unit tests

- Exercise pure domain decisions without FastAPI, SQLAlchemy, PostgreSQL, React, or real providers.
- Inject a controllable clock and deterministic test entropy through approved ports; do not weaken production randomness to make tests easier.
- Test both sides of exact temporal, length, range, state, and role boundaries.
- Verify rejected operations produce no domain transition or pending side effect.

## PostgreSQL integration

- Apply real Alembic migrations to a real supported PostgreSQL test database.
- Assert structural constraints, canonical uniqueness, encryption/digest storage shape, transactional state, idempotency, retention, and restart/recovery behavior.
- Do not use SQLite as a substitute for locks, isolation, partial indexes, PostgreSQL types, or concurrent constraints.
- Keep remote email and WhatsApp simulated unless a specifically approved provider test is in scope.

## Concurrency

- Use separate database connections and synchronize workers so they contest the same protected transition.
- Cover the races enumerated in the active plan: appointments/blocks, idempotent confirmation, reminders/deliveries, accounts, email claims, links, sessions, TOTP periods, recovery codes, rate limits, and deactivation.
- Assert at most the allowed successes, exact safe rejection behavior, no partial side effects, and valid final database state.
- Do not mistake parallel test execution for a deterministic concurrency test.

## Contract and security

- Test request/response schemas, status codes, headers, cookie attributes, CSRF, authorization, generic failures, rate limits, and partial provider outcomes.
- Compare authorized and unauthorized response fields so internal IDs, private codes, contacts, cancellation reasons, factors, tokens, or provider details cannot leak.
- Capture logs and audit records for sensitive flows and assert prohibited values are absent.
- Test the complete owner/staff/unauthenticated matrix at the backend even when the UI hides a control.
- Validate provider signatures/callbacks with controlled fixtures when those contracts are implemented; never call a real provider accidentally.
