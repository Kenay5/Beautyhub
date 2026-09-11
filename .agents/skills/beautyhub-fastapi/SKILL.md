---
name: beautyhub-fastapi
description: Design, implement, or review BeautyHub FastAPI HTTP adapters and Pydantic contracts while preserving domain isolation, the approved SQLAlchemy/Alembic stack, authorization boundaries, and sanitized responses. Use for backend web/API tasks, not for changing product requirements or dependencies.
license: MIT
---

# BeautyHub FastAPI

Use FastAPI as a thin delivery adapter around approved application use cases.

## Before working

Read `AGENTS.md`, `docs/constitution.md`, the active spec, its approved plan, and the selected task. Stop if the task would require an unapproved requirement, dependency, or stack change.

## Operating rules

- Keep domain and application rules independent of FastAPI, Pydantic, SQLAlchemy, PostgreSQL, React, and providers.
- Validate external shape at the HTTP boundary and enforce business invariants again in the domain and transaction where required.
- Obtain administrative identity and role from the server-side session context. Never accept client-supplied authority.
- Define explicit public response schemas that exclude secrets, internal identifiers, traces, SQL, and unauthorized personal data.
- Keep visible messages in Spanish and technical identifiers and logs in English.
- Follow the approved same-origin React/Vite delivery and session/CSRF design. Do not select a new CORS, session, or frontend-serving strategy from framework convenience alone.
- Do not add or replace dependencies. In particular, do not substitute SQLModel for SQLAlchemy/Alembic or `uv` for `pip`.

Read [references/api-boundaries.md](references/api-boundaries.md) for endpoint design, dependencies, async behavior, errors, and verification. Read [references/sources.md](references/sources.md) only for provenance or excluded upstream guidance.
