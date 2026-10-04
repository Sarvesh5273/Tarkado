# Finalized company workflow

**Status:** Accepted by the project owner on 2026-10-03.

This is the central reference for Tarkado's product workflow. Requirements,
roadmaps, and future implementation must follow it. Change an accepted decision
only with the owner's agreement and a dated entry in [DECISIONS.md](DECISIONS.md).
The workflow is finalized; the complete workflow is **not implemented yet**.

The owner requested an end-to-end completion goal on 2026-10-03. Remaining
implementation packages and completion criteria are tracked in
[TASKS.md](TASKS.md#completion-goal--first-end-to-end-tarkado-build). They do not
change W-01–W-08 or authorize deferred private-session access/live deployment.

## Company journey

```text
Company approves models, collection scope, and a safe default
                         ↓
Observe approved usage/outcomes from ALL developers
Do not change their model selection
                         ↓
Shadow mode: recommend a model for a task
Developer chooses manually; no extra model execution
                         ↓
Record the response to THAT recommendation
Senior accepts/rejects one task's recommendation
                         ↓
Record the model actually used and the task's actual result
Acceptance alone is not a successful outcome
                         ↓
Learn across tasks and sessions
Prioritize senior feedback; continue monitoring everyone
                         ↓
Report readiness for SPECIFIC supported task categories
Include failures, overrides, quality, cost, and evidence gaps
                         ↓
Designated senior/admin approves the FIRST automatic-routing pilot
Approve its policy version and limited scope, not every future task
                         ↓
Select models automatically for juniors AND seniors in that scope
Only at a new-task/run/subagent boundary; overrides remain available
                         ↓
Monitor everyone, retain senior feedback, and roll back if needed
Unsupported/uncertain work stays on the approved safe default
```

## Accepted decisions

| ID | Decision |
| --- | --- |
| W-01 | Initial observation covers all participating developers within company-approved collection scope. |
| W-02 | Early shadow mode is recommendation-only: developers choose manually, and Tarkado makes no additional alternative-model calls. |
| W-03 | A senior's accept/reject action concerns one task's recommendation, not approval of a team-wide routing policy. |
| W-04 | Link each recommendation, response, model actually used, and eventual task result. Acceptance plus a confirmed desired result is useful quality evidence; acceptance alone is preference evidence. |
| W-05 | Learn across tasks and sessions, giving senior feedback greater influence while continuing approved usage/outcome monitoring for everyone. |
| W-06 | Readiness is specific to evidenced task categories and model capabilities, never a blanket claim that Tarkado can route every task safely. |
| W-07 | A designated senior/admin must explicitly approve the first limited automatic-routing pilot. Confidence, training, per-task acceptance, or an offline report cannot enable it alone. |
| W-08 | After approval, automatic selection can serve juniors and seniors within that pilot's scope. Preserve developer overrides, safe fallback, monitoring, and reversibility; never switch an active task silently. |

## Two different approvals

**Per-task acceptance:** a senior accepts a suggestion such as "use the standard
model for this unit-test task." Record whether that model was actually used and
whether the result met the task's criteria. This adds feedback; it does not
enable company-wide routing or approve an unapproved provider/model.

**Pilot authorization:** a designated senior/admin reviews accumulated evidence
and approves a particular policy version, task categories, and limited rollout
scope. Future eligible tasks may then be selected automatically without asking
that reviewer to approve each individual task.

Accepting a suggestion but using a different model cannot establish that the
suggested model succeeded. Rejection, failure, override, and missing/unknown
results must remain visible. Senior feedback has greater influence, but is not
infallible or a reason to discard other developers' failures.

## Example

During shadow mode, Tarkado suggests a standard model for a senior's low-risk
test-writing task. The senior accepts, uses that model, and confirms the desired
result. Tarkado records that linked example alongside rejects and failures from
other tasks. It does not immediately route junior developers' work differently.

After evidence accumulates across tasks/sessions, Tarkado may propose a limited
pilot for that test-writing category. A designated senior/admin reviews and
authorizes the pilot. It can then select the approved model for eligible junior
and senior tasks. Authentication changes and other unsupported categories do
not inherit that permission.

This is an illustrative journey, not evidence that a particular model is safe.

## Shadow recommendations are not alternative-model experiments

In the agreed shadow workflow, only the developer's chosen model executes the
task through the existing coding tool/gateway. There is no hidden duplicate
request, alternative output, or extra shadow-test API bill.

Existing offline replay/candidate tools can compare already recorded outcomes.
They do not generate missing alternative outcomes. Any future isolated
alternative-model experiment requires separate company authorization, data
permission, and API budget; it is not an automatic part of shadow mode.

Learning uses outcomes for the models actually tried. It cannot invent how an
unused model would have performed. The feedback-learning method and evidence
requirements must be validated before claiming useful routing or savings.

## Current implementation versus the goal

Available supporting tools: local policy registry/rules, offline replay and
candidate reports, conditional uncertainty reporting, local history/rollback,
privacy checks/audits, and a mock-tested read-only session snapshot wrapper.

**Local linkage now available:** recommendation, per-task response, actual model,
and delayed/corrected result records, with declared developer roles and a
senior-prioritized ranking for manual review. See [FEEDBACK.md](FEEDBACK.md).
Links are validated, but outcome truth and role identities are not independently
verified.

**Experimental learning now available:** fit a count-based suggestion model
from an explicit validation plan, then supply it for future manual
recommendations. Source checks and conservative vetoes preserve negative
feedback; no policy is activated. See [LEARNING.md](LEARNING.md). This is not
validated production learning or a finalized evidence threshold.

**Local review now available:** category reports retain evidence gaps, and a
separately designated local senior/admin can approve/reject simulation scope.
Receipts bind report/policy/categories/developers. They do not authenticate
authority, enforce limits, or enable live routing. See
[READINESS_PILOT.md](READINESS_PILOT.md).

**Local pilot runtime now available:** explicit activation of a reviewed
simulation, scoped decisions, budget/task reservations, settlement, overrides,
pause/revocation, and default-only rollback. It preserves all history and makes
no model requests. Boundary/identity inputs remain declared rather than verified
by a live adapter; real deployment is not authorized.

**Actual account/company setup now available:** approved invitation-only
individual accounts, real password/session verification, protected administration,
current-role checks, and company policy/collection configuration. Required
administrator/approver authenticator MFA and restricted lost-factor backup
recovery are now implemented. Separate offline/admin-assisted password recovery
and fresh sensitive-action verification preserve MFA, roles, and history. The same
authenticated interface now links manual shadow suggestions, per-task responses,
reported actual models, and outcomes, retaining historical role snapshots. This
can run locally or via an implemented private-socket HTTPS-proxy serving contract;
no real company TLS/deployment validation or live adapter is claimed.
It does not retroactively authenticate legacy feedback/receipts or verify outcomes.
Stored category review and separately authenticated
**simulation** pilot approvals now reuse the existing learner/review and B-01
runtime, including current authority/expiry/revocation checks and preserved
accounting/rollback. B-02's live scope approval mechanics now require an additional
independent assessment from a trusted server-owned readiness verifier, plus the
designated human's separate fresh-MFA decision. The verifier defaults to refusal;
a live scope record is never model execution or deployment permission. The code
is tested with controlled evidence, not approved real company data. See
[COMPANY_OPERATIONS.md](COMPANY_OPERATIONS.md).

**Still missing:** automatic team-wide task capture, verified outcomes,
future learned manual-application integration, independent validation of the experimental learner,
an approved real readiness-verifier integration, verified company readiness,
trusted live scope/provider-budget integration, and live routing.
The snapshot wrapper is not task capture. A `policy review` label is not the
senior-feedback loop or authenticated pilot approval. Passing synthetic tests
does not prove the product works for real company tasks.

**Browser workflow now available (B-03):** readable tasks/pending states, guided
metadata and policy forms, labeled validation/scope/settlement selectors,
independent evidence inspection, exact-content confirmations, and readable
pilot guards/accounting/history reuse the existing company authority. See
[BROWSER_WORKFLOW.md](BROWSER_WORKFLOW.md). Task observation and outcomes remain
manual/unverified, and no coding-client connector or model call is added.

**Next priority:** separately scoped task integration and approved real
evaluation/trusted task-provider admission (B-04/B-05) through
the completed authorization boundary. B-02 account/authority mechanics are
implemented. Real evidence, separately granted live scope, safe admission, and
deployment validation remain required before any live execution.
Real-session validation remains deferred by the owner and does not block local
work on that loop. See [TASKS.md](TASKS.md).

**B-04 connector source now available:** explicit root-task start/end, scoped
browser-issued observation credentials, an append-only metadata API, and inactive
OpenCode V2 server/terminal plugin code reuse the same task/feedback records.
No Laya or automatic selection. Primary model attempts, permitted HTTP status,
retry metadata, and coverage gaps are diagnostics, not verified model use/results.
Category reviews bind these observations rather than silently ignore new gaps.
Installed OpenCode/TUI loading and approved real-session validation remain
unverified; automatic subagent capture and exact per-request usage are unsupported.
See [OPENCODE_CONNECTOR.md](OPENCODE_CONNECTOR.md). This does not complete B-04/B-05
or grant private-session access, provider execution, or live deployment.

**B-05 joined build now available:** explicit reviewed learner publication/default-
only reversal feeds future manual browser/connector suggestions and retains exact
historical snapshots. New feedback, junior negatives, and connector gaps preserve
safe fallback. Conditional live-scope selection/reservation/one-use claim/settlement
is implemented behind an additional server-owned admission verifier, default-denying.
Monitoring/withdrawal preserves accounting and never changes an in-flight model.
The actual atomic OpenCode/gateway task/model/provider-cap delivery adapter is still
unfinished, separately from owner-deferred installed-client/real-evidence/deployment
validation. No Laya, model/provider calls, or automatic live switching is enabled.
See [INTEGRATED_LEARNING_SELECTION.md](INTEGRATED_LEARNING_SELECTION.md).

## Not finalized yet

- The initial onboarding direction is accepted separately as C-01–C-05 in
  [DECISIONS.md](DECISIONS.md): self-hosted invitation-only individual accounts,
  explicit administrator/approver assignment, the same real laptop/company
  application, and optional later SSO. Django and the supported Python transition
  were subsequently approved; initial local login/setup/enrollment are implemented.
  Authenticated manual feedback preserves historical roles; approved django-otp
  now supplies authenticator MFA and limited lost-factor recovery. Approved
  offline/admin password recovery, scoped simulation controls, conditional live
  authorization mechanics, and company-serving code are implemented. The real
  readiness verifier, automatic capture/execution, and actual company deployment
  validation remain pending. No production criteria are inferred from test fixtures.
- How to verify the desired task result and capture task boundaries reliably.
- The learning method, senior-feedback weighting, and evidence/confidence
  requirements. Start with a simple baseline; tune on validation data, not
  held-out tests.
- Initial observation duration, minimum evidence, pilot limits, and rollback
  triggers. No numeric thresholds are agreed yet.
- How to handle disagreements, ignored suggestions, delayed results, and
  changes to a task's scope or risk.
- Whether later pilots can activate under preapproved evidence rules. This is
  a possible future option, **not approved behavior for the first pilot**.

Company-managed API/gateway credentials, metadata-first privacy, current model
approval/compatibility checks, and no production-savings claims from public or
synthetic results remain mandatory.
