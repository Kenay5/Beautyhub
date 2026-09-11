# Sources and adaptation

## Upstream source

- GitHub Spec Kit, `speckit-analyze` command template: <https://github.com/github/spec-kit/blob/main/templates/commands/analyze.md>
- Repository: <https://github.com/github/spec-kit>
- License: MIT, <https://github.com/github/spec-kit/blob/main/LICENSE>

This adaptation retains the read-only cross-artifact analysis, detection categories, severity model, traceability metrics, and concise reporting approach.

## Deliberately excluded

- `.specify/` initialization, discovery scripts, command placeholders, and its separate constitution path;
- extension hooks and automatic before/after commands;
- the requirement that `tasks.md` already exist, because BeautyHub also reviews specs and plans before tasks;
- automatic remediation commands or implementation suggestions when the user asks only for findings.

BeautyHub's existing `AGENTS.md`, `docs/constitution.md`, approved specs, and approved plans remain authoritative.
