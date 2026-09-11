---
name: beautyhub-frontend
description: Design, implement, or review BeautyHub React and TypeScript interfaces using the approved Vite architecture, responsive behavior, native accessibility, and clear UI states. Use for public or administrative frontend tasks; do not use it to choose a new framework, visual brand, dependency, or business rule.
license: MIT
---

# BeautyHub Frontend

Build the smallest interface that exposes the approved behavior clearly on mobile and desktop.

## Before working

Read `AGENTS.md`, `docs/constitution.md`, the active spec, approved plan, and selected task. Do not infer a visual system, workflow, field, state, or validation that the spec leaves undecided.

## Core boundaries

- Use React, TypeScript, and Vite as approved. Do not introduce Next.js, server components/actions, SWR, a component library, state library, CSS framework, or another dependency without approval.
- Keep business decisions in framework-independent application/domain code. Frontend validation improves feedback but never becomes the only integrity or authorization control.
- Render only data authorized by the relevant public or administrative contract. Role-based hiding is usability, not security.
- Keep administrative session secrets out of browser persistence and follow the approved HttpOnly cookie and in-memory CSRF design.
- Preserve Spanish visible content and English code, identifiers, test names, logs, and technical messages.

For React composition and performance decisions, read [references/react-vite.md](references/react-vite.md). For semantic HTML, keyboard/focus, forms, responsive behavior, and evidence, read [references/accessibility-responsive.md](references/accessibility-responsive.md). Read [references/sources.md](references/sources.md) for provenance and excluded upstream guidance.
