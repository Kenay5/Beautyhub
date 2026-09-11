# Sources and adaptation

## Upstream source

- Official FastAPI Skill: <https://github.com/fastapi/fastapi/blob/master/fastapi/.agents/skills/fastapi/SKILL.md>
- Repository: <https://github.com/fastapi/fastapi>
- License: MIT, <https://github.com/fastapi/fastapi/blob/master/LICENSE>

Retained guidance includes typed inputs, `Annotated` dependencies, explicit response filtering, router-level shared concerns, one HTTP operation per function, and avoiding blocking calls inside asynchronous functions.

## Deliberately excluded or constrained

- SQLModel preference: BeautyHub has approved SQLAlchemy and Alembic.
- `uv`, Ruff, ty, Asyncer, or HTTPX as automatic additions: no dependency or tool may be introduced without approval.
- `app.frontend()` as an unconditional requirement: availability must be checked against the pinned version and approved delivery design.
- SSE and streaming guidance: no active BeautyHub requirement currently needs it.
- generic examples that place behavior directly in routes: BeautyHub keeps domain and application logic framework-independent.
