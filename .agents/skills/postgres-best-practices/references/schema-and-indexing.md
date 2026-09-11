# Schema and indexing

## Schema decisions

- Model only entities and states anchored in the active spec and approved plan.
- Use database constraints for invariants expressible within a row or stable uniqueness scope: required values, enums, ranges, canonical uniqueness, single active records, and one-use identifiers.
- Protect cross-row and time-dependent rules in the approved domain transaction, reinforced by locks, conditional writes, unique indexes, or guard rows as the plan requires.
- Store money using an exact numeric representation and timestamps as absolute instants; evaluate business time in `America/Mexico_City` through the approved clock policy.
- Store searchable secrets as keyed digests and recoverable sensitive values only through the approved authenticated-encryption design. Do not put readable secrets or personal data into diagnostic columns.
- Preserve immutable snapshots and consent/audit relationships exactly where the approved spec requires historical evidence.

## Index decisions

- Start from actual approved lookups, ordering, foreign keys, uniqueness, and retention scans. Do not add speculative indexes.
- Prefer a single composite or partial index whose order matches the real predicate over several redundant indexes.
- Remember that an index accelerates reads but adds write, storage, migration, and maintenance cost.
- Use `EXPLAIN (ANALYZE, BUFFERS)` only with safe non-production data or an explicitly authorized environment. A guessed plan is not performance evidence.
- Recheck query plans after representative data volume exists; a development table with a few rows is not representative.

## Query safety

- Use bound parameters through the approved adapter; never interpolate untrusted input into SQL.
- Select only fields authorized by the contract. Authorization remains required even if a row identifier is opaque.
- Bound list sizes and pagination according to an approved contract; do not invent limits in the data layer.
- Treat accent/case normalization, exact matches, and canonical forms according to the spec rather than database defaults.
