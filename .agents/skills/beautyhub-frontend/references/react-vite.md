# React and Vite guidance

## Component and state design

- Organize components around user tasks and meaningful UI boundaries, not around every data field or backend entity.
- Keep transport mapping in a small client boundary and present components with the minimum typed data they need.
- Derive values during render when possible. Do not copy props or server data into state without a synchronization requirement.
- Put user-triggered behavior in event handlers instead of effects. Use effects only to synchronize with an external system and give them precise dependencies and cleanup.
- Use functional state updates when the next value depends on the previous value.
- Do not add `useMemo`, `useCallback`, memoization, caching, or abstraction without observed cost or a stable identity requirement.
- Avoid defining component types inside other components and avoid broad barrel imports when direct imports keep bundles and ownership clearer.
- Start independent approved requests together when doing so cannot violate ordering, session, rate-limit, or transaction semantics. Never parallelize dependent mutations.

## Data and interaction states

- Model loading, success, empty, validation error, authorization error, conflict, rate limit, provider partial failure, and retry state only when the active contract can produce them.
- Prevent accidental duplicate submissions in the interface while relying on backend idempotency and concurrency protection as the authority.
- Keep the original user input available when a recoverable validation error occurs unless the security design requires clearing a secret.
- Do not reveal whether an account, private code, or appointment exists when the contract requires a generic response.
- Clear passwords, TOTP, recovery codes, link tokens, private appointment codes, and transient QR data from UI memory when their approved display window ends.
- Do not place secrets in URLs, localStorage, sessionStorage, analytics, console output, or client logs.

## Vite and delivery

- Use the repository's approved Vite scripts and npm lockfile. Do not substitute Next.js conventions or package-manager commands.
- Keep environment-specific public configuration free of secrets; browser bundles cannot protect a value merely because it came from an environment variable.
- Verify the production build as served under the same origin by FastAPI, including client-side route fallback and API route precedence.
- Defer performance optimizations until bundle, render, or interaction evidence identifies a material issue. Correct behavior and accessibility remain required.
