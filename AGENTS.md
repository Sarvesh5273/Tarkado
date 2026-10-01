# Engineering Rules for Lanesmith

## Product guardrails

- Build a policy/evaluation layer, not a generic LLM gateway.
- Assume company-managed API/gateway credentials, never consumer subscriptions.
- Route at new-task or subagent boundaries; do not silently switch models in a
  live session.
- Default to safe fallback when evidence, compatibility, or confidence is
  missing.
- Do not claim production savings from public benchmark data.

## Development rules

- Use `.venv/bin/python` for every Python command.
- Keep raw prompts, source code, traces, outputs, API keys, and tokens out of
  Git by default.
- Write plain-language comments in code.
- Explain technical terms with a short bracketed definition when communicating
  with the project owner.
- Keep all matrices/data columns in their declared canonical order.
- Never weaken or remove an assertion to make a run pass. Print the relevant
  values and stop instead.
- Choose tuning parameters on validation data, never on held-out test data.
- Print complete numerical output; do not hide negative or unclear results.
- Prefer a simple baseline before adding an advanced model or decision system.

## Research rules

- Use primary documentation or papers for claims about external products.
- State when a claim is a hypothesis rather than established fact.
- Benchmark against existing approaches before claiming novelty.
- Treat user overrides and failures as important evaluation signals.
