---
name: postgres-best-practices
description: Design, implement, or review BeautyHub PostgreSQL schemas, indexes, migrations, transactions, concurrency controls, retention, and recovery. Use for persistent-data work with the approved SQLAlchemy/Alembic stack; do not use it to introduce new infrastructure or product behavior.
license: Apache-2.0
---

# Postgres Best Practices

Apply PostgreSQL guidance only within the active BeautyHub spec, approved plan, and selected task.

## Workflow

1. Identify the exact invariant, query, retention rule, or failure mode being implemented.
2. Decide which layer protects it: PostgreSQL constraint/index, transaction and locking, domain validation, or a deliberate combination.
3. Keep SQLAlchemy and Alembic as the approved adapters. Do not replace them or make the domain depend on them.
4. Design migrations that work from an empty database and the preceding approved revision. Never treat SQLite as evidence for PostgreSQL-specific behavior.
5. Verify races with independent PostgreSQL connections and observable final invariants, not only sequential tests.

Read [references/schema-and-indexing.md](references/schema-and-indexing.md) for schema/query work. Read [references/transactions-and-operations.md](references/transactions-and-operations.md) for locking, migrations, retention, backup, restore, or deployment work. Read [references/sources.md](references/sources.md) for provenance and upstream topics intentionally left optional.

Do not enable extensions, replication, RLS, PgBouncer, another datastore, or another persistent service without an approved requirement and explicit dependency/infrastructure approval.
