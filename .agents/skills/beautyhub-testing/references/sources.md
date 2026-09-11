# Sources and adaptation

## Upstream sources

- OpenAI `frontend-testing-debugging`: <https://github.com/openai/plugins/blob/main/plugins/build-web-apps/skills/frontend-testing-debugging/SKILL.md>
- OpenAI plugins repository and MIT manifest: <https://github.com/openai/plugins/blob/main/plugins/build-web-apps/.codex-plugin/plugin.json>
- Microsoft debugpy `pytest` Skill: <https://github.com/microsoft/debugpy/blob/main/.claude/skills/pytest/SKILL.md>
- Microsoft debugpy license: MIT, <https://github.com/microsoft/debugpy/blob/main/LICENSE>

Retained guidance includes narrow fixtures, factory fixtures, readable parametrization, observable assertions, independent tests, a repeatable browser interaction loop, console/render checks, screenshot evidence, and explicit residual risk.

## Deliberately excluded or constrained

- `pytest-cov`, `pytest-mock`, `pytest-asyncio`, `pytest-xdist`, `pytest-timeout`, or any plugin as an automatic dependency.
- `pnpm` commands and ad hoc Playwright installation; BeautyHub approved npm and a repository Playwright configuration.
- automatic code edits during a QA-only request.
- one generic mobile viewport as sufficient evidence; BeautyHub's active plans define the required sizes, browser projects, and real-device gates.
- browser-plugin installation suggestions and plugin-specific routing as a completion condition.
- 100 percent line coverage as a substitute for RF/EARS and risk-based evidence.
