# API security review method

Use the OWASP API Security Top 10 as a question set, not as a source of new product requirements.

## Review map

1. **Object-level authorization (API1):** verify that a public private code yields only its appointment and that every administrative object operation derives authority from the server session. Opaque identifiers do not replace authorization.
2. **Authentication (API2):** inspect password handling, TOTP and recovery consumption, session creation/replacement/expiry, link expiry, account state, generic errors, and atomic credential use.
3. **Property-level authorization (API3):** compare every input and output field with the actor's approved fields. Look for mass assignment, database-model serialization, leaked internal references, secrets, contacts, or cancellation reasons.
4. **Resource consumption (API4):** verify specified IP/account limits, Argon2 concurrency bounds, bounded queries, provider retries, and behavior at exact windows. Do not invent new thresholds.
5. **Function-level authorization (API5):** exercise the complete owner/staff/unauthenticated matrix in the backend, including less-visible endpoints and rejected mutations.
6. **Sensitive business flows (API6):** inspect booking confirmation idempotency, private-code access, reminder retries, invitations, password reset, email change, factor replacement, and bootstrap for replay or automation abuse.
7. **SSRF (API7):** inspect only features that accept or derive outbound destinations. Provider URLs and callbacks must come from trusted configuration; do not invent a URL-fetching feature.
8. **Security configuration (API8):** review cookie flags, CSRF, Origin/Referer checks, CSP and cache/referrer headers, trusted proxies, production debug settings, secret loading, and dependency versions already approved.
9. **Inventory (API9):** compare implemented routes and methods with approved contracts; flag undocumented, legacy, debug, duplicate, or accidentally public endpoints.
10. **Unsafe API consumption (API10):** validate provider responses and authenticated callbacks, apply timeouts/idempotency, sanitize provider failures, and prevent provider data from deciding domain authorization or state directly.

## Cross-cutting checks

- Concurrency: one valid final state for contested appointments, links, email claims, sessions, TOTP periods, recovery codes, rate limits, and deliveries.
- Privacy: no real personal data in tests; no secrets or complete personal data in URLs, logs, audit events, errors, screenshots, traces, or metrics.
- Retention and restore: expired data must be inaccessible at the logical boundary and restored security material must not revive access.
- Provider isolation: an email/WhatsApp failure must preserve the exact safe state in the specs and must not reveal internal provider details.
- Frontend: hidden controls are not authorization; browser storage must follow the approved cookie/CSRF design.

## Evidence and reporting

For each confirmed finding record severity, affected actor/object/action, exact source location, reproduction or reasoning, impact, affected requirement, and evidence boundary. Use critical only for a demonstrated path to major unauthorized access, secret exposure, or systemic integrity loss. Label speculative paths as needing verification.

When only a review was requested, propose no fix unless the user asks. Never include live secrets or harmful exploit material in the report.
