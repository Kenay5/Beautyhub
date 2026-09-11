# Review method

Load only the artifacts required by the request, but read every selected file completely before judging it.

## Detection passes

1. **Authority:** identify any plan, task, implementation note, or test expectation that changes or weakens the constitution or approved spec.
2. **Contradiction:** compare actors, permissions, states, time boundaries, data fields, error behavior, retention, security controls, and out-of-scope declarations.
3. **Ambiguity:** flag wording that permits materially different observable results or leaves security, data, cost, operation, or architecture undecidable.
4. **Duplication:** report repeated rules only when they can drift, conflict, or obscure which statement controls. Harmless summaries are not defects.
5. **Edge cases:** inspect exact inclusive and exclusive boundaries, invalid states, retries, partial failures, concurrent requests, expiry, restoration, and unavailable providers.
6. **Traceability:** map every RF and EARS criterion to plan design and, when tasks exist, at least one task and verification. Identify tasks with no approved requirement.
7. **Verification quality:** ensure critical behavior is not covered only by UI tests; ensure PostgreSQL-specific invariants and races have PostgreSQL integration evidence.
8. **Cross-feature consistency:** compare shared terminology, roles, authorization, notification, retention, responsive targets, and dependency gates without merging feature ownership.

## Severity

- **Critical:** contradicts the constitution, exposes private or administrative data, changes an approved requirement, or leaves core behavior without any implementation/test path.
- **High:** contradictory requirements, untestable security behavior, missing authorization/integrity boundary, or an implementation decision that cannot satisfy the spec.
- **Medium:** meaningful ambiguity, uncovered edge case, terminology drift, incomplete non-functional verification, or risky duplication.
- **Low:** editorial inconsistency that does not change behavior or execution.

Do not inflate severity merely because a document is long. A declared and correctly gated deferred decision is not an ambiguity.

## Report contract

Lead with findings ordered by severity and then source location. For each finding provide:

- stable finding ID;
- category and severity;
- exact artifact and location;
- observed conflict or gap;
- affected identifiers;
- why it matters.

When the user asks only for detection, do not propose solutions. Otherwise place remediation proposals after findings and never apply them automatically.

After findings, report:

- artifacts and approval states reviewed;
- counts of RF and EARS criteria derived from the current files;
- unmapped requirements and unanchored tasks;
- constitution conflicts;
- assumptions, deferred gates, and residual review limits.

Use deterministic identifiers and counts so an unchanged rerun produces comparable results. Aggregate repetitive low-value findings instead of flooding the report.
