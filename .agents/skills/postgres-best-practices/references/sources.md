# Sources and adaptation

## Upstream source

- Neon `postgres-best-practices`: <https://github.com/neondatabase/postgres-skills/tree/main/skills/postgres-best-practices>
- Repository: <https://github.com/neondatabase/postgres-skills>
- License: Apache-2.0, <https://github.com/neondatabase/postgres-skills/blob/main/LICENSE>

The automated GitHub installer was denied by the environment's permission gate before downloading. This local version is therefore an attributed adaptation based on the reviewed public Skill, not a byte-for-byte installation.

Retained areas are schema design, indexing, query analysis, transaction isolation, migration safety, backup/restore, roles, and connection management.

## Deliberately constrained

- Logical replication, hot standby, bulk-loading infrastructure, RLS, PgBouncer, extensions, and major-version upgrade machinery are not default BeautyHub requirements.
- Provider-specific Neon operation is excluded; BeautyHub's approved deployment target is Railway.
- The upstream version support table is not copied because it becomes stale; version selection remains an explicit implementation/deployment task.
