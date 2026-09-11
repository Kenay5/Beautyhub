# Accessibility and responsive guidance

Accessibility evidence is successful task completion and recovery, not an Axe score alone.

## Semantics and forms

- Prefer native elements and behavior before ARIA. ARIA may describe semantics; it does not supply keyboard interaction or visual behavior.
- Give every form control a persistent programmatic label. Associate hints and errors with the relevant control and announce important dynamic results appropriately.
- Keep instructions and errors specific enough to recover, except where security requires deliberately generic wording.
- Preserve paste and password-manager autocomplete in authentication fields as required by the active spec.
- Use headings, landmarks, lists, tables, buttons, and links according to their purpose. Do not turn a clickable `div` into the default control.

## Keyboard and focus

- Every action must be reachable and operable with a keyboard in a logical order.
- Keep focus visibly distinguishable and do not remove the browser outline without an equivalent replacement.
- Move focus only when the interaction requires it, such as a validated dialog workflow or route result; restore it to a logical control when a transient surface closes.
- A hidden, disabled, loading, expired, or rejected state must remain understandable without relying only on color.

## Responsive and touch behavior

- Start from the narrow layout and preserve all approved content and actions from 320 CSS pixels upward.
- Use fluid layout and content-driven adjustments. Avoid fixed dimensions that create page-level horizontal scrolling, clipping, overlap, or unreachable controls.
- Administrative tables may scroll inside their own container only under the exception already approved by the specs and must retain labels, headers, focus, and actions.
- Do not block browser zoom. Verify text and controls at enlarged zoom and with long Spanish labels, validation messages, and representative data.
- Follow the plans' product target for comfortably operable touch areas; do not replace it with a smaller generic minimum.

## Evidence

- Exercise the task at the sizes and browsers required by the active plan, including the 320-pixel boundary.
- Check keyboard order, focus, labels, error association, zoom/reflow, color independence, touch usability, and screen-reader names for the affected flow.
- Run Axe in the approved Playwright journeys, but never claim complete WCAG conformance from automated results.
- Record any untested browser, assistive technology, real device, or state as residual risk. Manual Android and iPhone checks remain release gates where the specs require them.
