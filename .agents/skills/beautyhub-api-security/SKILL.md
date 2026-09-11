---
name: beautyhub-api-security
description: Review BeautyHub API, authentication, authorization, privacy, abuse controls, and provider boundaries against the approved threat model and OWASP API risks. Use for explicit security design, review, hardening, or security-test tasks; not for ordinary feature work or unsanctioned active testing.
license: CC-BY-4.0
---

# BeautyHub API Security

Produce evidence-based security work without changing the product contract.

## Select the authorized mode

- **Design or document review:** read-only; compare spec, plan, contracts, threats, and controls.
- **Code review:** read-only unless the user explicitly asks to fix findings.
- **Security testing:** use only the test environment and techniques explicitly authorized by the task. Never probe production, external accounts, or third-party providers by implication.
- **Hardening implementation:** requires an approved task and any separate approval needed for dependencies, configuration, or infrastructure.

## Workflow

1. Read `AGENTS.md`, `docs/constitution.md`, the active spec and plan, and the selected task.
2. Inventory public, administrative, scheduled, provider-callback, and recovery entry points that actually exist in scope.
3. Map actors, objects, allowed operations, sensitive fields, trust boundaries, and concurrent transitions.
4. Apply [references/review-method.md](references/review-method.md). Link every finding to concrete evidence and affected RF/EARS criteria where available.
5. Separate confirmed vulnerabilities, defense-in-depth suggestions, and untested hypotheses. Do not report tool output as proof without validation.
6. Stop before installing scanners, sending exploit payloads to a live target, changing dependencies, or expanding infrastructure.

Do not prescribe JWT, OAuth, an API gateway, a WAF, Redis, or another security product when BeautyHub's approved opaque-session/PostgreSQL design satisfies the requirement. Read [references/sources.md](references/sources.md) for attribution and excluded upstream rules.
