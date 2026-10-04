# Synthetic offline fixtures

These records are hand-written metadata for fictional `fixture/*` models. They
contain no real prompts, source code, provider results, credentials, or customer
data. The policy's evidence references are illustrative labels, not proof of
model quality.

The dataset deliberately includes a cheaper route that fails tests, unknown
outcomes, a missing cheap-model outcome, a developer override, a high-risk
security task, and a context-capacity fallback. Do not use these results to
claim production savings or to approve a real model.

`synthetic.jsonl` has one baseline per task and at most one outcome per
task/model. `rollout.jsonl` has three distinct low-risk tasks with two samples
each, one baseline per task/sample, and a cheaper candidate with a test failure
and score regressions. `rollout-plan.json` uses illustrative predeclared count
gates; these are not statistically validated rollout thresholds.

Neither fixture can approve a real model. The candidate remains in candidate
state after evaluation, and statistical deployment approval is unimplemented.

`uncertainty-plan.json` demonstrates the interval calculations with explicit
synthetic sampling-assumption labels. These labels do not verify statistical
independence or representativeness. The same negative rollout fixture remains
unchanged and still yields reject; the plan is not a production configuration.

`feedback-demo.json` contains explicit fictional senior/junior observations for
the local linkage loop. It demonstrates accepted/unexecuted recommendations,
wrong-model attribution, successful senior adoption, a junior failure, and a
senior rejection. Importing it does not execute any model or verify real roles,
outcomes, savings, training, or routing eligibility.

`learning-plan.json` supplies illustrative validation settings for the
experimental count-based learner. `learning-docs-task.json` and
`learning-tests-task.json` are future-session metadata requests, not real coding
tasks. Fitting/application performs no model calls and proves no production
quality, savings, or routing readiness.

`pilot-scope.json` and `pilot-approvers.json` declare a fictional documentation
simulation and local reviewer labels. Limits are examples, not production
defaults. These receipts never authorize live deployment, authenticate an
approver, or execute/enforce a budget.

`pilot-request.json` and `pilot-settlement.json` drive the local runtime
demonstration after explicit review/activation. They reserve fictional cost
capacity and settle a supplied fictional cost. No model is run; `completed`
is not a verified quality outcome or a training success label.
