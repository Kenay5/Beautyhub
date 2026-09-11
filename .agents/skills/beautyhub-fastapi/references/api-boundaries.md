# FastAPI boundary guide

## Contracts

- Give each HTTP operation one focused path-operation function and delegate promptly to an application use case.
- Use typed Pydantic input and output contracts. Prefer explicit return types; use a separate response model when the internal object contains more data than the public contract.
- Express required fields without ellipsis and avoid `RootModel` when an ordinary annotated type describes the contract clearly.
- Put shared path prefixes, tags, and genuinely shared dependencies on the router.
- Never expose database models directly. Translate transport data at the boundary.
- Preserve the exact HTTP behavior approved in the plan. Framework defaults do not override specified generic errors, partial notification success, or authorization results.

## Dependencies and security context

- Use `Annotated[..., Depends(...)]` for reusable request dependencies when supported by the pinned FastAPI version.
- Dependencies may load a session, create request-scoped resources, or adapt infrastructure; they must not hide business decisions.
- For administrative state changes, validate the approved session cookie, Origin/Referer policy, CSRF token, account state, and role before invoking the use case.
- Public appointment secrets and security-link tokens belong in request bodies, never paths or query strings.
- Treat proxy-derived IP information as authoritative only when the deployment's trusted-proxy configuration is approved.

## Sync and async

- Use `async def` only when every blocking operation called in that path is awaited through an approved asynchronous API.
- Use ordinary `def` when the approved database/provider adapter is synchronous; FastAPI can execute it outside the event loop.
- Do not hold a PostgreSQL transaction open while waiting on email, WhatsApp, or another remote provider when the approved flow records an intent first.
- Do not introduce an async helper, driver, queue, or client merely to follow a generic framework recommendation.

## Errors and observability

- Translate expected validation, authorization, conflict, rate-limit, and provider outcomes into the statuses defined by the approved plan.
- Return stable, sanitized error bodies. Public authentication and lookup failures must not become distinguishable through wording or unauthorized fields.
- Log only controlled technical events in English. Redact private codes, confirmation references, passwords, TOTP, recovery codes, session tokens, CSRF tokens, email addresses, phone numbers, and provider payloads.
- Validate response filtering with contract tests; a type annotation alone is not evidence that an internal secret cannot escape.

## Frontend delivery

BeautyHub serves the compiled Vite application from the FastAPI deployment under the approved same origin. Choose the concrete serving mechanism only after checking the pinned FastAPI/Starlette versions. Do not assume a newly documented API exists and do not add a package solely for static delivery without approval.

## Verification

- Unit-test business behavior below the FastAPI layer.
- Contract-test schemas, statuses, headers, cookies, CSRF, generic errors, and authorization.
- Integration-test PostgreSQL transactions and concurrency against PostgreSQL, not an in-memory substitute.
- Exercise complete browser flows with the repository's approved Playwright configuration.
