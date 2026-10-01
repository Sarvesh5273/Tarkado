# Lanesmith

> Forge safe model lanes for engineering teams using multi-model coding tools
> such as OpenCode.

## The problem

Engineering teams increasingly use several coding models through company API
accounts. Developers understandably choose strong, expensive models when they
are unsure, which can make API spend grow quickly. At the same time, a new
model may be cheaper or better for some tasks—but enabling it blindly can hurt
code quality, reliability, or security.

Existing gateways can forward requests, track cost, set budgets, and retry
failures. Lanesmith is intended to answer the higher-level question:

> Given this team's own coding tasks and evidence, which approved model should
> handle this new task, and is a newly released model safe to enable?

## What Lanesmith will do

```text
Developer starts a task in a multi-model coding tool
                    ↓
Lanesmith reads approved task metadata and policy
                    ↓
Choose cheap / standard / premium model tier
                    ↓
Existing tool or gateway sends the request
                    ↓
Record cost, latency, outcome, override, and policy version
```

For a new candidate model, Lanesmith will support a safe rollout loop:

```text
Observe → evaluate → shadow-test → limited pilot → enforce → monitor/rollback
```

## What it will not do in v1

- Replace OpenCode, LiteLLM, OpenRouter, or another gateway.
- Use or automate employees' consumer ChatGPT/Claude subscriptions.
- Switch a live Claude Code session into Codex/Gemini midway through a task.
- Promise savings without measuring quality, task outcomes, and developer
  overrides.
- Send raw source code or prompts to a central server by default.

## Target user

A small engineering team that:

- uses a provider-neutral coding CLI/IDE such as OpenCode;
- has company-managed API keys or an existing gateway;
- has more than one approved coding model;
- wants lower cost without silently lowering engineering quality.

## Documentation

| File | Purpose |
| --- | --- |
| [PRD.md](docs/PRD.md) | Product requirements and user workflow. |
| [TRD.md](docs/TRD.md) | Technical requirements and proposed architecture. |
| [TASKS.md](docs/TASKS.md) | Ordered build roadmap and acceptance checks. |
| [DECISIONS.md](docs/DECISIONS.md) | Decisions, assumptions, and unresolved choices. |
| [RESEARCH.md](docs/RESEARCH.md) | Market/research evidence and differentiation. |
| [AGENTS.md](AGENTS.md) | Engineering rules for future implementation work. |

## Project status

**Planning only.** No runtime code has been written yet. The first build goal
is an offline policy simulator, not a production gateway.
