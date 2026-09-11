# Frontend and end-to-end verification

## Playwright workflow

1. Define the flow as entry state, user action, and expected rendered result.
2. Use the repository's `npm` and Playwright scripts and its configured integrated application. Do not substitute `pnpm` or create a second test harness.
3. Establish page identity, meaningful content, absence of framework overlays, and relevant console health.
4. Exercise the target interaction and assert the resulting visible state plus the durable backend outcome where applicable.
5. Run the browser projects, sizes, and journeys required by the active plan. At minimum, preserve the approved Chromium, Firefox, and WebKit coverage and representative 320, 390, 768, and 1280 CSS-pixel layouts.
6. Keep screenshots, traces, and temporary debug scripts outside the repository unless the task explicitly approves committed evidence.

An interactive browser may help diagnose a rendered failure, but it does not replace the reproducible Playwright suite.

## Accessibility and responsive evidence

- Check page-level horizontal overflow, clipping, overlap, missing content, unreachable controls, scroll traps, and long Spanish messages.
- Operate the complete affected flow using the keyboard and verify logical order, visible focus, dialogs/overlays, labels, names, descriptions, and associated errors.
- Verify zoom/reflow and that status, error, selection, and permission meaning never relies only on color.
- Run `@axe-core/playwright` in the approved main states and investigate every reported violation. A clean automated scan is not a complete accessibility verdict.
- Record manual Android, iPhone, screen-reader, touch, or browser-version checks as pending until actually executed on the required environment.

## Security-sensitive UI

- Confirm private appointment codes appear only in their approved confirmation context and never in screenshots or reports containing real data.
- Confirm passwords, TOTP secrets, recovery codes, security-link tokens, CSRF tokens, and session tokens are absent from URLs, persistent browser storage, console logs, and unintended screens.
- Confirm generic login/recovery/link failures remain indistinguishable and that frontend role restrictions match backend denials.

## Result report

State the environment, command, flow, browser/viewport, result, evidence, failures, and remaining risk. A build pass does not prove rendered behavior; a Chromium pass does not prove the full approved browser matrix.
