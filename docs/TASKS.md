# Lanesmith Build Roadmap

## Phase 0 — Product foundation

- [x] Create product, technical, research, decisions, and task documents.
- [ ] Choose final repository name.
- [ ] Choose an open-source licence.
- [ ] Create Git repository and initial commit after name/licence decision.
- [ ] Interview or simulate the workflow of at least three engineering teams:
  how they select models, track spend, and test new models.

**Done when:** the first user/problem statement is sharper than “reduce LLM
costs.”

## Phase 1 — Offline policy simulator

- [ ] Create a Python project with reproducible dependency management.
- [ ] Define and validate `TaskTrace`, `PolicyDecision`, and
  `RolloutReport` schemas.
- [ ] Add fixture datasets with cheap, standard, and premium model outcomes.
- [ ] Implement deterministic historical replay.
- [ ] Implement explainable static policies based on task/risk tags.
- [ ] Implement default-model fallback for every invalid/unknown decision.
- [ ] Add unit tests proving observe/shadow modes do not enforce routing.
- [ ] Add a readable local CLI report.

**Done when:** a local CSV/JSONL file produces a reproducible policy comparison
report without calling a real API.

## Phase 2 — New-model rollout evaluator

- [ ] Add candidate-model registry state: candidate/shadow/approved/disabled.
- [ ] Add baseline-versus-candidate report: cost, latency, outcome, failures,
  variation, and compatibility.
- [ ] Add recommendation states: enable / shadow / collect more evidence /
  reject.
- [ ] Add policy versioning and rollback metadata.
- [ ] Add a constant/no-change baseline so the evaluator cannot claim a gain
  without comparison.
- [ ] Add repeated sampling/uncertainty reporting for research datasets.
- [ ] Test an old benchmark dataset only as an offline research fixture; do not
  claim production results from it.

**Done when:** a new candidate model can be evaluated and produce a transparent
go/no-go recommendation.

## Phase 3 — Privacy and safety

- [ ] Implement metadata-only mode.
- [ ] Implement raw-content opt-in configuration.
- [ ] Add secret scanning/redaction before trace export.
- [ ] Add policy allowlist: only approved providers/models may be chosen.
- [ ] Add risk-tag rule: high-risk/unknown tasks fall back to the default
  premium model.
- [ ] Add audit event format for every policy decision and override.

**Done when:** a team can explain what data is stored and why every routing
decision occurred.

## Phase 4 — OpenCode adapter (observe-only first)

- [ ] Read the current OpenCode V2 plugin/client documentation before coding.
- [ ] Decide whether the first adapter is a plugin, command wrapper, or local
  proxy; document the choice.
- [ ] Read model/provider metadata from approved OpenCode configuration only.
- [ ] Capture permitted new-task/subagent-boundary events in observe mode.
- [ ] Map compatible model capabilities into Lanesmith's registry.
- [ ] Verify no active model choice changes in observe mode.
- [ ] Add integration tests using a local/mock provider.

**Done when:** Lanesmith can observe an OpenCode workflow without exposing API
keys or changing a developer's selected model.

## Phase 5 — Shadow and pilot routing

- [ ] Return a Lanesmith recommendation at a new task/subagent boundary.
- [ ] Show the suggested model, reason, confidence, fallback, and override
  option to the developer.
- [ ] Add shadow-mode reporting of proposed versus actual model selection.
- [ ] Add limited-scope pilot configuration: repository/team/task tags.
- [ ] Add rollback to the default policy.
- [ ] Measure developer overrides as a first-class quality signal.

**Done when:** a small team can test a policy without losing control of its
coding workflow.

## Phase 6 — Existing-gateway exports

- [ ] Design a stable policy YAML/JSON format.
- [ ] Research LiteLLM export/integration constraints.
- [ ] Add one gateway-policy exporter only after the local format stabilises.
- [ ] Document unsupported cross-agent/provider combinations clearly.

**Done when:** Lanesmith can hand a versioned, explainable policy to an
existing gateway rather than becoming another gateway.

## Phase 7 — Optional intelligence improvements

- [ ] Establish simple-rule and random-selection baselines first.
- [ ] Evaluate embeddings or retrieval for similar-task matching.
- [ ] Evaluate active task selection for new-model testing.
- [ ] Evaluate Laya only against the same data, policy, and latency budget.
- [ ] Keep an advanced method only if it improves a measured result.

**Done when:** every “smart” feature beats a simple baseline or is removed.
