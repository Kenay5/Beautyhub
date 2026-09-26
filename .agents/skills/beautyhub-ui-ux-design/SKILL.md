---
name: beautyhub-ui-ux-design
description: Review and direct BeautyHub interface visual design and UX against the applicable approved mockup and design guide. Use for visual direction or review of public/admin screens; not as the primary React implementation or test guide.
---

# BeautyHub UI/UX Design

Use this skill to decide how an in-scope BeautyHub screen should look and feel. Produce concrete visual direction, or review the rendered screen against it. This is the design-direction skill—not the primary guide for implementing React or proving behavior.

## Authority and scope

- Follow `docs/constitution.md`, the active approved spec, its approved plan, and the active task before visual guidance.
- Use `docs/design/DESIGN_GUIDE.md` for the approved visual system and `docs/design/admin/` or the public design references for screen-specific direction.
- Select only the mockup that corresponds to the active flow. Do not browse or borrow from unrelated screens to fill gaps. If no applicable mockup exists, rely on the design guide and approved requirements; do not invent a screen or product behavior.
- A mockup is a visual reference, not authority for fields, permissions, copy, states, or behavior. Do not implement a visual detail that conflicts with the spec or plan.
- Limit review and changes to the requested screen and its directly necessary responsive/error states. Do not redesign neighboring or unrelated screens.

## Design workflow

1. Identify the exact task, user, screen, entry point, success/error/loading/blocked states, and RF/CA constraints.
2. Read only the applicable design-guide sections and exact screen mockup. Describe the reference’s structure and hierarchy before proposing changes.
3. Translate that reference into specific decisions for:
   - composition, content width, alignment, and card/form layout;
   - heading/subheading hierarchy and approved typography;
   - spacing and grouping, field dimensions, labels, borders, radii, and surfaces;
   - primary/secondary actions, placement, prominence, and separation;
   - feedback, loading, error, blocked, expired, and success presentation;
   - responsive reflow at required widths and preservation of all approved content/actions.
4. Prefer the established BeautyHub tokens and patterns in `DESIGN_GUIDE.md`. Keep decoration subordinate to the user’s task and do not add fonts, icons, component libraries, or dependencies without approval.
5. Small departures from a mockup are acceptable only to improve usability, accessibility, or responsive behavior while preserving the spec. State the reason; do not use this as permission to change behavior or visual brand.
6. Review the rendered interface explicitly. Inspect screenshots at relevant breakpoints and states; do not equate passing Playwright, Axe, or a successful build with visual approval. Record any states/device checks not visually reviewed as pending.

## Visual and inclusive-quality checks

- At 320, 390, 768, and 1280 CSS px (when required by the task), preserve information and actions, avoid page-level horizontal overflow, clipping, overlap, and unreachable controls.
- Keep visible labels, clear grouping, readable text hierarchy, consistent field and button geometry, adequate touch targets, and a clearly dominant primary action.
- Use text and structure as well as color for selection and status. Place errors near affected controls, associate them accessibly, and preserve generic security wording where required.
- Check keyboard order, visible focus, semantics, zoom/reflow, and Axe; automated results are evidence, not a complete accessibility or visual verdict.
- Keep user-visible BeautyHub content in Spanish. Do not add unsupported marketing claims or copy product details from a mockup that are outside the approved behavior.

## Relationship to other BeautyHub skills

- `beautyhub-ui-ux-design` decides how the screen should look and feel, using the right approved references.
- `beautyhub-frontend` governs how to implement an approved design correctly in React/TypeScript/Vite and preserve frontend architecture/accessibility.
- `beautyhub-testing` governs how to verify journeys, responsive/accessibility behavior, and residual manual checks.

Use the frontend and testing skills alongside this one when the task includes implementation or verification. Keep responsibilities separate and never let visual guidance redefine requirements.
