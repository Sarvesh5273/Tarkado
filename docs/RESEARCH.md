# Research and Market Context

This document records the evidence behind the product direction. It is not a
claim that Lanesmith is the first router.

## 1. Existing infrastructure: do not rebuild it

### LiteLLM

LiteLLM already provides an OpenAI-compatible proxy, virtual keys, spend
tracking, budgets, fallbacks, routing, and logging. Lanesmith should integrate
with this type of gateway rather than recreate it.

- [LiteLLM routing](https://docs.litellm.ai/docs/routing)
- [LiteLLM budgets and rate limits](https://docs.litellm.ai/docs/proxy/users)

### OpenRouter

OpenRouter offers generic Auto routing and a Jev decision-model router. It can
apply allowed/excluded candidate lists and organization spending controls.

- [OpenRouter Auto Router](https://openrouter.ai/docs/guides/routing/routers/auto-router)
- [OpenRouter Jev Router](https://openrouter.ai/docs/guides/routing/routers/jev-router)
- [OpenRouter organization controls](https://openrouter.ai/docs/guides/features/guardrails)

### Claude Code gateway support

Claude Code documents organization gateways for credentials, usage tracking,
cost controls, audit logging, and provider switching. It also warns that
Anthropic does not support routing Claude Code to non-Claude models through a
third-party gateway.

- [Claude Code gateway documentation](https://docs.anthropic.com/en/docs/claude-code/llm-gateway)

### OpenCode

OpenCode V2 supports multiple providers, custom compatible endpoints, model
selection per session/run, and model selection for agents/commands. This makes
it a good first integration target for provider-neutral model selection.

- [OpenCode providers](https://opencode.ai/v2/docs/providers)
- [OpenCode models](https://opencode.ai/v2/docs/models/)

## 2. Existing research: do not overclaim novelty

- [RouteLLM](https://github.com/lm-sys/RouteLLM) is an established framework
  for serving/evaluating routers, with a strong-vs-weak model focus.
- [ContextualRouter](https://aclanthology.org/2026.eacl-srw.22/) studies
  retrieval-based routing and adding/removing models without retraining.
- [ICL-Router](https://arxiv.org/html/2510.09719v3) studies adding new models
  via in-context model representations without router retraining.
- [Routing and cascading survey](https://github.com/ymoslem/awesome-llm-routing-cascading)
  shows a large and active research space.

## 3. Product differentiation hypothesis

The gap is not “route an LLM request.” The gap to test is:

> Can an engineering team turn private task traces into a transparent,
> versioned, safe policy for model choice and new-model rollout without
> replacing its existing coding tool or gateway?

This is a hypothesis. It must be tested through developer interviews, a useful
local workflow, and an integration that saves engineering time—not merely via a
benchmark chart.

## 4. Why company API accounts, not employee subscriptions

- ChatGPT subscriptions and API use are billed separately.
  [OpenAI billing documentation](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform)
- Claude paid plans and API usage are billed separately.
  [Anthropic support](https://support.anthropic.com/en/articles/9876003-i-subscribe-to-claude-pro-why-do-i-have-to-pay-separately-for-api-usage-on-console)
- OpenAI prohibits sharing account credentials, reselling access, and automated
  extraction in the stated Pro terms.
  [OpenAI Pro terms](https://help.openai.com/en/articles/9793128-about-chatgpt-pro-tiers)

Therefore Lanesmith assumes company-owned API/gateway credentials for any
shared routing or budget enforcement.

## 5. Evaluation data reality

Small companies may have raw task traces but not curated labelled evaluation
sets. Lanesmith must distinguish these conditions instead of assuming “50
prompts” means enough evidence.

- [LangSmith evaluation docs](https://docs.langchain.com/langsmith/evaluation)
  describe datasets created from curated cases, historical production traces,
  and synthetic data.
- [Braintrust datasets docs](https://www.braintrust.dev/docs/annotate/datasets)
  describe datasets from production logs, user feedback, and manual curation.

Product implication:

```text
No usable evaluation cases → help create/collect cases; do not claim routing confidence.
Some cases             → observe and shadow-test only.
Sufficient evidence    → recommend a limited pilot.
```
