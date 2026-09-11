# Attribution and adaptation

## Upstream source

- OWASP Secure Agent Playbook, `api-security-review`: <https://github.com/OWASP/secure-agent-playbook/blob/main/plugins/code-security-skills/skills/api-security-review/SKILL.md>
- Repository: <https://github.com/OWASP/secure-agent-playbook>
- License: Creative Commons Attribution 4.0 (CC BY 4.0), <https://github.com/OWASP/secure-agent-playbook/blob/main/LICENSE>
- Methodology referenced upstream: OWASP API Security Top 10 2023, OWASP ASVS, and OWASP Web Security Testing Guide.

This derivative adaptation preserves attribution and the OWASP API risk taxonomy while narrowing the process to BeautyHub's approved architecture and authorization boundaries.

## Deliberately excluded or constrained

- Mandatory ZAP, Burp Suite, Postman, or other scanner execution.
- Reconnaissance or active attack traffic against production, real accounts, or providers.
- JWT, OAuth, API-key, mTLS, API-gateway, or WAF prescriptions when those mechanisms are not in the approved design.
- automatic fixes, dependency additions, infrastructure changes, and remediation roadmaps outside the requested task.
- the upstream relative `plays/` dependency; the relevant review questions are self-contained in `review-method.md`.

Any adapted or redistributed material remains subject to CC BY 4.0 attribution requirements.
