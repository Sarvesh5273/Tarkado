# Product and Architecture Decisions

This file prevents the project from drifting. A decision can be changed, but
the reason and date must be recorded.

## Finalized company workflow — 2026-10-03

**Accepted by the project owner.** [WORKFLOW.md](WORKFLOW.md) is the central
product reference, including stable decision IDs W-01 through W-08.

- Observe all participating developers within approved company collection scope.
- Start with recommendation-only shadow mode: manual model selection, no extra
  alternative-model executions.
- Senior accept/reject feedback concerns one task's recommendation, not a
  team-wide policy.
- Link each recommendation and response to the model actually used and eventual
  result. Acceptance alone is preference, not proof of quality.
- Learn across tasks/sessions; prioritize senior feedback without stopping
  everyone else's usage/outcome monitoring or discarding failures.
- Report readiness for specific supported categories, not all tasks universally.
- Require designated senior/admin authorization of the first limited automatic-
  routing pilot. Training, confidence, or per-task acceptance cannot activate it.
- After approval, automatic selection may serve juniors and seniors in the
  approved scope, with overrides, fallback, monitoring, and rollback.

These decisions replace any earlier implication that evidence alone enables a
pilot or that a shadow recommendation runs alternative models. They do not
change the existing code's implementation status. Future changes to this
workflow require owner agreement and a dated change-log entry.

## Company onboarding and delivery — accepted 2026-10-03

The owner approved the following direction and requested implementation. These
decisions supplement W-01–W-08; they do not authorize live data access or routing.

| ID | Accepted decision |
| --- | --- |
| C-01 | Build one self-hosted company application around the existing `engine/`, with a company-controlled source of permissions and pilot state. Do not rebuild completed components or become a model gateway. |
| C-02 | The initial login path uses invitation-only individual Tarkado accounts. The installation owner explicitly appoints the first administrator, who invites the team. No existing company SSO or corporate email domain is required. |
| C-03 | Use the same application and actual login/permission checks for laptop demonstrations and company installations. Demonstrations may use isolated, clearly labeled synthetic evidence, which cannot authorize live requests or prove production readiness. |
| C-04 | Existing company SSO is an optional later integration, not a prerequisite or required initial-release provider implementation. |
| C-05 | Company membership, seniority, administration, and designated pilot-approval permission are assigned explicitly. Signup, email ownership, login, and per-task acceptance alone grant no company/pilot authority. |

Use maintained authentication components rather than hand-written password or
cryptographic systems. The owner subsequently approved Django 5.2 LTS and the
transition from Python 3.9 to installed Python 3.13, with the old environment
preserved under Git-ignored `local/`. This is separate dependency/environment
authorization, not permission to install unrelated packages. Initial operator
enrollment and private manual invitations are implemented. The owner separately
approved django-otp for required administrator/approver authenticator MFA and
single-use lost-factor backup recovery, now implemented. The owner subsequently
approved private offline/admin-assisted password recovery and Waitress single-host
serving behind a reviewed HTTPS proxy. Those implementations and authenticated
simulation authorization/runtime controls now exist. Positive conditional live
scope approval is now implemented against a default-denying trusted readiness
interface. Actual company readiness verification, task/provider admission, and
deployment validation remain separate, unfinished live-use gates.
See [COMPANY_AUTHORIZATION.md](COMPANY_AUTHORIZATION.md).

## B-03 interface direction — accepted 2026-10-04

The owner accepted the browser-first recommendation after reviewing the distinction
between a skill, a company interface, and coding-client integration.

| ID | Accepted decision |
| --- | --- |
| UI-01 | Build B-03 as a usable browser workflow on the existing Django application/templates, not a new skill, desktop application, or replacement frontend/backend. Reuse B-02 identity/authority and the existing record contracts. |
| UI-02 | Keep company evidence review, separate human pilot approval, and administrative controls in the authenticated company service. Skills may later provide optional help, but agent instructions never establish identity, outcome truth, or approval authority. |
| UI-03 | Add a narrow developer-facing coding-tool connector separately in B-04. OpenCode CLI plugins are a candidate for displaying task suggestions/actions; the capture/authentication/task-boundary mechanism remains to be validated before implementation. Do not assume one plugin works across other clients or switch active tasks. |

The proposed CLI experience may include a small prompt status and an on-demand
task panel; commands such as `/tarkado` are illustrative and do not exist yet.
The official V2 CLI plugin guide documents commands, footer slots, and session
panels, but those UI capabilities do not themselves authenticate company roles or
establish a trusted task boundary. Other clients require their own supported
adapter/capability checks. No new package/plugin installation, private-session
access, model calls, or automatic selection is authorized by these UI decisions.

## Active decisions

### B-04 implementation direction — accepted 2026-10-04

The owner accepted the narrow OpenCode V2 connector and requested implementation,
after explicitly agreeing that B-04 does **not** use Laya. Start with explicit
developer task boundaries, automatic permitted metadata observation, code-enforced
collection/storage, manual model recommendations, and existing company authority.
No plugin/dependency installation, private-session access, provider requests, or
live routing is authorized by this implementation request. Unverified host/event
capabilities must remain visible; subagent/automatic boundary inference is not
assumed. B-05 learning/automatic selection remains separate. Optional Laya research
does not alter this decision without a separately approved evaluation.

### Build-phase verification boundary — owner clarification 2026-10-04

The owner requested continuing B-05 construction and deferring installed-client,
real-session/company evidence, and deployment checks until later. Regression tests,
scope/privacy/approval checks, and conservative fallback remain mandatory. This
does not authorize private-session access, dependencies, provider calls, first-pilot
self-approval, or a live-session model-switch shortcut. Conditional publication/
selection interfaces can be built and tested with isolated evidence now; missing
actual task/model/provider delivery software must remain explicitly unfinished,
not relabeled as only deferred validation.

### Local commit authorization — 2026-10-04

The owner requested logical commit batches and a push. Review found that the
existing GitHub repository is public and no implementation licence has been
chosen. When asked, the owner selected **Keep code unpublished**: local commits
are authorized, but public push is deferred until a licence is explicitly chosen.
Do not infer a licence or push the implementation under the earlier request.
Local stores, credentials, environments, and private session data remain excluded.

The unfinished automatic-delivery adapter is not blocked only by testing. Current
official OpenCode V2 documentation covers explicit run/session model choice and
request hooks, but does not establish an atomic company task/model/hard-cost-cap
contract. Choose and verify one concrete company gateway/provider admission path
before claiming that adapter can be completed; tests must exercise that path.
No new provider/gateway, credentials, live calls, or dependency is selected here.

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
| Prioritize the recommendation-response-actual-model-outcome loop next. | Supporting evaluation tools do not yet capture senior feedback or learn company recommendations. | Accepted |
| Use Tarkado as the product/repository name and `engine/` for application code. | Keep the product identity while avoiding a confusing nested same-name folder. | Accepted |
| Use Python's standard library for the first offline implementation. | No runtime dependency installation is needed to run or test the simple baseline. | Accepted |
| Use approved Django 5.2 LTS for the optional company login/setup application, on supported Python. | Reuse maintained password/session components instead of custom authentication; preserve the dependency-free offline engine and original environment. | Accepted on 2026-10-03 |
| Use approved django-otp for administrator/designated-approver authenticator MFA and single-use backup recovery. | Require real second-factor verification; recovery grants factor replacement only, not pilot authority. Preserve existing account/task state. | Accepted on 2026-10-03 |
| Use private one-use offline recovery credentials and MFA-verified administrator-assisted recovery after separate identity confirmation. | Avoid mandatory email/SSO; preserve MFA, roles, revoked access, and history; invalidate sessions/grants. All-lost recovery cannot invent trusted identity. | Owner approved; recorded 2026-10-04 |
| Use approved Waitress for one private single-host company service behind an operator-configured HTTPS proxy. | Do not expose Django's development server as company deployment; require exact origin, private transport/state, secure cookies, and reviewed operational prerequisites. | Owner approved; recorded 2026-10-04 |
| Require paired, recorded task/model outcomes for replay comparisons. | Missing cheaper-model outcomes cannot establish cost or quality improvements. | Accepted |
| Treat policy exports as local proposals, not rollout approvals. | Exporting supplied rules must not imply their evidence was verified or a live model was enabled. | Accepted |
| Keep candidate/shadow models unroutable until explicitly approved. | Evaluating an outcome is not permission to send a new live task to that model. | Accepted |
| Candidate evaluation compares the current policy and recorded no-change baseline separately. | A candidate must not claim a gain merely by ignoring an existing better routing policy. | Accepted |
| Only conservative reject/shadow/collect-more-evidence advice is implemented initially. | Missing evidence or a small synthetic fixture cannot authorize enablement; every report keeps deployment unauthorized. | Accepted |
| Require explicit task/sample pairing and predeclared count gates. | Repeated outcomes must not be mistaken for additional independent tasks or tuned to held-out results. | Accepted |
| Store local policy snapshots and history in one locked JSON file. | Simple local storage permits complete validated writes and avoids introducing a database for this milestone. | Accepted |
| Bind local review labels to immutable policy content, not only a version name. | A changed policy must not reuse an old review or silently overwrite the same version. | Accepted |
| Keep local selection/rollback separate from model approval and live routing. | Restoring a local snapshot cannot authorize a new model or change an active session. | Accepted |
| Require the expected current version for local selection changes. | A stale operator decision must not replace a newer selection silently. | Accepted |
| Reject suspected secrets instead of silently rewriting routing metadata. | Redacting model IDs, risk labels, or evidence references could change a decision's meaning. | Accepted |
| Keep raw-content collection unsupported during the offline privacy milestone. | Metadata-only evaluation must work before higher-risk collection is considered. | Accepted |
| Export per-task audits explicitly, with hashed identifier references and exact policy fingerprints. | Preserve decisions, failures, and overrides without exporting raw task content or misbinding a report to a reused version label. | Accepted |
| Declare audit retention as manual until deletion management is reviewed. | Do not imply automatic expiry or delete potentially user-owned data without a dedicated policy. | Accepted |
| Use an explicit OpenCode V2 CLI GET wrapper for the first observation adapter. | Reuse installed service/authentication without a plugin dependency or a new gateway; keep session selection unchanged. | Accepted |
| Keep session snapshots separate from task traces and evaluation evidence. | Cumulative counters and runtime status do not identify individual tasks or prove engineering quality. | Accepted |
| Never treat resolved OpenCode catalog capabilities as independently verified team policy. | Official V2 docs describe custom-model fallback assumptions and location/plugin settlement effects. | Accepted |
| Use equal-task weighting and a simple Hoeffding bounded-quality interval baseline. | Avoid pretending repeated runs are independent tasks or that small observed variance proves safety. | Accepted |
| Withhold intervals for incomplete coverage or unattested independent/fixed sampling. | Caller metadata cannot establish a justified inferential conclusion by itself. | Accepted |
| Keep cost/latency uncertainty descriptive until hard bounds are justified. | Observed sample ranges are not guaranteed population bounds. | Accepted |

## Explicit non-decisions yet

| Question | Current position | When to decide |
| --- | --- | --- |
| Product-name availability | Tarkado is the selected product name; trademark/domain availability has not been verified. | Before a public release. |
| Open-source licence | Do not choose blindly. | Before publishing code. |
| Storage format/database | Local JSONL/CSV first. | When traces exceed local-file needs. |
| Exact quality scorer | Could include tests, review, human ratings, or LLM judge. | During offline evaluator design. |
| Senior-feedback learning method and weighting | Greater influence is accepted; exact weights, aggregation, and retraining method are not chosen. Start with a validated simple baseline. | During feedback-loop implementation. |
| Desired-result verification and disagreements | Link actual results to tasks; define criteria, missing-result handling, and review conflicts without treating acceptance as success. | Before readiness claims. |
| Developer roles and pilot-approver identity | Actual accounts/roles/MFA/recovery and simulation/live authorization mechanics are implemented. A live scope needs a server-owned independent readiness assessment plus a separate fresh-MFA designated human decision. The verifier is unconfigured/default-denying; actual company evidence and deployment validation remain deferred. See [COMPANY_OPERATIONS.md](COMPANY_OPERATIONS.md). | Before actual company approval/deployment, not another B-02 identity rebuild. |
| Evidence/confidence gates and pilot limits | No numeric thresholds, observation duration, or rollout/rollback triggers have been approved. | Validate before automatic routing. |
| Later self-activating pilots | Preapproved evidence rules are a possible future option, not authorization for the first pilot. | Revisit after validating a reviewed pilot. |
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
| Automatic company routing immediately after one senior accepts a suggestion | Per-task feedback is not a scoped routing-policy authorization. |
| Quietly executing extra models in shadow mode | The agreed shadow workflow suggests alternatives without duplicate execution or hidden API spend. |
| Stop observing junior developers after senior feedback arrives | Senior feedback is prioritized; approved usage/outcome monitoring continues for everyone. |

## Change log

| Date | Change |
| --- | --- |
| 2026-10-01 | Initial product direction established. |
| 2026-10-03 | Confirmed Tarkado naming, `engine/` source layout, and dependency-free offline baseline. |
| 2026-10-03 | Kept rollout-report implementation in Phase 2; Phase 1 exports only local policy proposals. |
| 2026-10-03 | Implemented conservative offline candidate reports; formal uncertainty, reviewed enablement, and rollback remain pending. |
| 2026-10-03 | Implemented local policy snapshots, explicit review labels, and rollback; authenticated approval and live rollback remain pending. |
| 2026-10-03 | Added conservative secret-pattern checks, private offline audits, and report-to-policy fingerprints; broader privacy and live capture remain pending. |
| 2026-10-03 | Selected a read-only OpenCode V2 snapshot wrapper; live hooks are deferred until a safe typed task-boundary contract is verified. |
| 2026-10-03 | User deferred real-session validation; implemented conservative offline uncertainty without changing rollout gates. |
| 2026-10-03 | Owner finalized recommendation-first company workflow, senior-prioritized per-task feedback plus actual outcomes, and explicit senior/admin approval for the first automatic-routing pilot. Recorded in WORKFLOW.md; feedback-loop implementation is the next priority. |
| 2026-10-03 | Added the local feedback/result linkage baseline with declared roles and immutable/correctable history. Preliminary senior-prioritized ranking is for manual review only; production learning weights, outcome verification, readiness gates, and pilot authorization remain unfinalized/unimplemented. |
| 2026-10-03 | Implemented explicit validation-plan count-based learning and manual future application. Experimental requirements are caller-supplied, not finalized production thresholds; source checks retain known negative feedback, and no pilot activation is granted. |
| 2026-10-03 | Implemented category-review and designated senior/admin local simulation receipts. Kept identity unverified, declared limits unenforced, and deployment/routing disabled; trusted live authorization remains future work. |
| 2026-10-03 | Owner requested a goal to complete the remaining building work. Recorded B-01–B-07 and end-to-end completion criteria in TASKS.md; preserved accepted workflow, deferred live access, unresolved technical choices, and separate deployment gates. |
| 2026-10-03 | Implemented B-01 local scoped pilot simulation. Reservations/settlements preserve overruns and history; default-only rollback does not restore a live deployment. Company identity, actual provider budgeting, and live admission remain unimplemented. |
| 2026-10-03 | Recovered the 372-test baseline and proposed B-02 company setup/trusted authorization in COMPANY_AUTHORIZATION.md. Deployment, identity verification, and administrator bootstrap remain owner choices; the proposal is not an accepted mechanism or authorization to deploy. |
| 2026-10-03 | Owner clarified that Tarkado must be a real company product also demonstrable on the laptop, and raised startups without company login. Updated the B-02 proposal so existing SSO is not assumed; standalone individual accounts are proposed but not selected, and no framework/dependency or live access is approved. |
| 2026-10-03 | Owner accepted self-hosted invitation-only individual accounts, an explicitly appointed first administrator, and the same real application on the laptop, with optional company SSO later. Recorded C-01–C-05 and began B-02. Framework/dependency and supported-Python choices remain separate; real-session access, provider requests, and live deployment stay deferred. |
| 2026-10-03 | Owner separately approved Django 5.2 LTS and a preserved-environment transition to installed Python 3.13. Implemented initial real account/company setup with private manual invitations and explicit permissions; 421 tests pass. B-02 remains partial: recovery/MFA, joined trusted task/pilot operations, and company deployment are unfinished. |
| 2026-10-03 | Continued B-02 by joining authenticated accounts to manual task recommendations/responses/reported models/outcomes and preserving per-record role snapshots in an additive schema-2 projection. Added task tables and explicit account-preserving upgrade; 469 tests pass. W-01–W-08 and schema-1 behavior remain unchanged. Actual outcomes and task boundaries remain unverified; company learning/review, recovery/MFA, trusted pilots, and deployment are unfinished. |
| 2026-10-03 | Clarified initial bootstrap after the owner tried an empty store; 471 tests passed. Owner then approved django-otp and authenticator MFA/lost-factor backup recovery. Implemented required privileged proof and restricted recovery; 501 tests pass. Forgotten-password/operator recovery, trusted policy/scope pilot authorization, and protected deployment remain pending; neither MFA nor recovery enables routing. |
| 2026-10-04 | Owner requested full B-02 and approved offline/admin-assisted recovery and Waitress single-host HTTPS-proxy serving. Implemented those mechanisms, category evidence, authoritative fresh-MFA simulation approvals/rejections/revocation, B-01-backed accounting/controls, and private backup; 540 tests pass. Includes joined browser flow and downgrade/serving safety checks. Kept full B-02 incomplete rather than relabel manual evidence as verified live readiness; private/live access remains deferred. |
| 2026-10-04 | Owner confirmed the remaining B-02 scope is live-authorization mechanics and tests, while real evidence, task/provider integration, and deployment validation are separate gates. Completed conditional live approval using a server-owned readiness-verifier interface with default refusal, exact identity/content/scope/validity checks, and immutable withdrawal history; 573 tests pass. Marked B-02 implementation complete without changing W-01–W-08, claiming a real verifier, enabling execution, installing packages, or authorizing live access. |
| 2026-10-04 | Owner accepted B-03 browser-first Django interface direction and requested explanation of the future in-tool experience. Recorded UI-01–UI-03 after checking official OpenCode V2 skills/plugins/CLI documentation. Documentation/design only: existing UI/authority code is preserved; no connector/skill/plugin was installed or claimed complete, and live access remains deferred. |
| 2026-10-04 | Owner accepted no Laya for B-04 and requested the explicit-task connector build. Implemented scoped delegated browser/API records and inactive V2 server/CLI plugin source, preserving manual choice, privacy, negative/unknown signals, and separate company approval authority. 637 Python and 14 JavaScript tests pass; installed TUI/host and approved real-session validation remain pending. No dependencies/plugin activation, private sessions, provider calls, user-store changes, or live routing. |
| 2026-10-04 | Owner deferred real-client/company checks during build and requested B-05. Implemented learner publication/reversal/future manual guidance and conditional exact-scope selection/accounting behind separate readiness and atomic-admission gates. 671 Python and 19 JavaScript tests pass. Missing actual capped new-task delivery remains unfinished software, not a validation checkbox; no live switch/provider/private access/dependencies/activation/commits/pushes. |
