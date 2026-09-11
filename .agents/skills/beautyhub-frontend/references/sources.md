# Sources and adaptation

## Upstream sources

- OpenAI `react-best-practices`: <https://github.com/openai/plugins/blob/main/plugins/build-web-apps/skills/react-best-practices/SKILL.md>
- OpenAI plugins repository: <https://github.com/openai/plugins>
- Plugin manifest license: MIT, <https://github.com/openai/plugins/blob/main/plugins/build-web-apps/.codex-plugin/plugin.json>
- Magnus `web-accessibility`: <https://github.com/magnus919/agent-skills/blob/main/web-accessibility/SKILL.md>
- Repository: <https://github.com/magnus919/agent-skills>
- `web-accessibility` license: MIT, declared in its Skill frontmatter.

Retained guidance includes eliminating avoidable request waterfalls, direct imports, derived state, event-driven interaction logic, native semantics, keyboard/focus behavior, recoverable forms, responsive input, and evidence that combines automated and manual checks.

## Deliberately excluded or constrained

- Next.js pages, React Server Components, server actions, `next/dynamic`, hydration-specific workarounds, and Next.js server caching.
- SWR, `better-all`, analytics, component libraries, and other automatic dependency recommendations.
- generic browser-storage optimizations that conflict with BeautyHub's prohibition on persisting session/security secrets in the browser.
- a new accessibility contract or blanket WCAG conformance claim; the active specs define the required scope and device/browser matrix.
- the upstream 24-by-24 target as a replacement for BeautyHub's approved 44-by-44 product target.
- automatic visual redesign or invented brand requirements.
