# Transactions and operations

## Transactions and concurrency

- State the invariant and all rows that can affect it before choosing a lock.
- Re-read mutable state inside the transaction immediately before committing a protected transition.
- Acquire locks in a stable order to reduce deadlocks. Treat deadlocks or serialization failures as explicit outcomes; retry only when the approved use case is idempotent and the retry policy is defined.
- Use unique constraints and conditional updates as final defenses for one-owner, one-session, one-link, one-code-use, one-reminder, and idempotency guarantees described by the active plan.
- For schedule mutations, use the approved shared agenda guard and revalidate appointments, blocks, service state, duration, branch separation, and time limits in the same transaction.
- Commit the business operation and durable delivery intent before contacting a remote provider when the plan specifies that pattern.
- Test races with separate connections synchronized at the contested point. Assert both accepted/rejected outcomes and the final database state.

## Alembic migrations

- Keep each revision focused and review generated SQL before applying it.
- Provide deterministic upgrade behavior from the last approved schema and from an empty database.
- Plan table rewrites, locks, backfills, constraints, and rollback/recovery before production execution.
- Obtain the required pre-schema-change backup and verify its recoverability under the approved operational procedure.
- Do not edit an already deployed migration to hide a correction; add a new revision unless the project is demonstrably pre-deployment and the task explicitly approves consolidation.

## Retention, backup, and restore

- Queries must exclude expired records at the exact approved boundary even if physical cleanup is delayed.
- Cleanup jobs must be idempotent, bounded, and safe to resume after interruption.
- Follow the specs' distinct retention rules for appointments, administrative history, delivery data, and disassociated statistics.
- Use the deployment provider's approved encrypted backup mechanism and retention window. Do not infer that a local Docker volume is a production backup.
- Restore into an isolated environment, invalidate restored security state as required, run pending retention/removal, and verify health before admitting traffic.

## Runtime scope

Use the selected supported PostgreSQL major version at its latest minor release. Size connection pools for the actual Railway resource and application concurrency. Replication, hot standby, logical decoding, partitioning, RLS, extensions, and external poolers remain optional architecture decisions, not defaults.
