---
name: beautyhub-spec-review
description: Review BeautyHub SDD artifacts for authority conflicts, ambiguity, contradiction, duplication, missing edge cases, and RF/EARS traceability. Use when auditing a spec, plan, tasks file, or cross-feature consistency; do not use it to implement the product.
license: MIT
---

# BeautyHub Spec Review

Perform a high-signal, evidence-based review of BeautyHub's Spec-Anchored artifacts.

## Workflow

1. Read the repository `AGENTS.md`, `docs/constitution.md`, and every artifact explicitly in scope. Determine each artifact's approval state; do not infer approval from existence.
2. Apply the repository authority order. A lower-level artifact may explain implementation, but it may not redefine a higher-level requirement.
3. Build inventories using the exact HU, RF, EARS, RNF, decision, risk, and task identifiers present in the documents. Do not create substitute requirements.
4. Use [references/review-method.md](references/review-method.md) for detection, severity, traceability, and report rules.
5. Cite concrete file locations for every finding. Distinguish a confirmed defect from a question or deferred gate.
6. Keep the review read-only unless the user separately and explicitly approves specific edits. Never initialize GitHub Spec Kit or create `.specify/` artifacts.

If a material decision is absent, explain why it matters and ask one focused question. If there are no material findings, say so directly and report the coverage boundary checked.

Read [references/sources.md](references/sources.md) only when provenance, licensing, or adaptation choices are relevant.
