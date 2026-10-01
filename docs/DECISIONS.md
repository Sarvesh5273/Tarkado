# Product and Architecture Decisions

This file prevents the project from drifting. A decision can be changed, but
the reason and date must be recorded.

## Active decisions

| Decision | Why | Status |
| --- | --- | --- |
| Target engineering teams, not consumer subscription users. | Company API costs, policies, and outcome signals are controllable. | Accepted |
| Support provider-neutral coding tools such as OpenCode first. | One tool can choose among multiple configured models. | Accepted |
| Route at task/subagent boundaries, not mid-session. | Safer and easier to explain/debug. | Accepted |
| Build a policy/evaluation layer, not a new generic gateway. | LiteLLM/OpenRouter/gateways already solve transport, budgets, and failover. | Accepted |
| New model starts as candidate/shadow, never default. | Avoid silent quality regressions. | Accepted |
| Use company API/gateway credentials only. | Consumer subscriptions are separate from APIs and unsuitable for shared routing. | Accepted |
| Keep Laya optional. | It must prove better latency, label efficiency, or policy quality. | Accepted |
| Start offline before a live plugin. | Prevent expensive/insecure integration work before the core policy works. | Accepted |

## Explicit non-decisions yet

| Question | Current position | When to decide |
| --- | --- | --- |
| Final project/repository name | `Lanesmith` is the selected working/project name; verify trademark/domain availability before a public release. | Before public repository creation. |
| Open-source licence | Do not choose blindly. | Before publishing code. |
| Storage format/database | Local JSONL/CSV first. | When traces exceed local-file needs. |
| Exact quality scorer | Could include tests, review, human ratings, or LLM judge. | During offline evaluator design. |
| Active-learning algorithm | Useful possibility, not a claim yet. | After random-selection baseline exists. |
| First gateway export | Likely LiteLLM/OpenRouter-compatible policy. | After local policy format stabilises. |
| Laya integration | Optional research track. | Only after baseline is measured. |

## Rejected directions

| Rejected direction | Reason |
| --- | --- |
| Generic “another LLM router” | Crowded ecosystem; weak open-source differentiation. |
| Routing employees’ ChatGPT/Claude subscriptions | Separate API billing, policy/terms risk, no shared budget control. |
| Browser automation of consumer AI products | Fragile, unsafe, and not a company-grade integration. |
| Immediate full Claude Code ↔ Codex ↔ Gemini switching | Different agent protocols and session semantics make this unsafe for v1. |
| Chatbot-only product | Too narrow; first product supports evaluable coding workflows. |

## Change log

| Date | Change |
| --- | --- |
| 2026-10-01 | Initial product direction established. |
