"""Versioned policy handoff, never a portable approval or execution credential."""

from django.db import transaction

from engine.feedback import _fingerprint
from engine.learning import LearnedModel
from engine.privacy import ensure_safe
from engine.readiness import PilotScope, _digest
from engine.schemas import Policy, ValidationError, integer, object_fields, text
from .connectors import uuid_value
from .delivery import envelope_for
from .selection import _state
from .models import ScopedSelectionRuntime


FIELDS = ("schema_version", "kind", "reference_path", "company_id", "deployment_id", "company_revision",
          "scope_ref", "scope", "policy", "policy_sha256", "learner", "learner_content_sha256", "model_bindings",
          "compatibility", "unsupported", "execution_credential", "portable_live_approval", "routing_enabled", "sha256")
REFERENCE = "OpenCode V2 -> LiteLLM Proxy -> company-managed OpenAI API"
COMPATIBILITY = {"opencode_source_version": "2.0.21", "litellm_candidate_version": "1.104.0",
                 "protocol": "text-chat-completions-v1", "boundary": "explicit-fresh-root-session",
                 "model_switching": False, "client_streaming": "buffered-from-one-nonstream-provider-response",
                 "provider_streaming": False, "tools": False, "installed_host_validation": "separately_required"}
FUNCTION_COMPATIBILITY = {**COMPATIBILITY, "protocol": "bounded-local-function-chat-v2", "tools": "reviewed_client_owned_functions",
                          "hosted_tools": False, "unrestricted_shell": False}


def validate(value):
    object_fields(value, FIELDS, FIELDS)
    ensure_safe(value)
    if type(value["schema_version"]) is not int or value["schema_version"] not in (1, 2) or value["kind"] != "tarkado_existing_gateway_policy" or value["reference_path"] != REFERENCE:
        raise ValidationError("Unsupported versioned gateway policy handoff.")
    if value["execution_credential"] is not False or value["portable_live_approval"] is not False or value["routing_enabled"] is not False:
        raise ValidationError("A policy handoff cannot contain portable live authority or execution permission.")
    for field in ("company_id", "deployment_id", "scope_ref"):
        uuid_value(value[field])
    if integer(value["company_revision"], "company_revision") == 0:
        raise ValidationError("Policy handoff requires a positive company revision.")
    for field in ("policy_sha256", "learner_content_sha256", "sha256"):
        _digest(value[field], field)
    if value["sha256"] != _fingerprint({key: val for key, val in value.items() if key != "sha256"}):
        raise ValidationError("Policy handoff content changed.")
    policy = Policy.from_dict(value["policy"])
    learner = LearnedModel.from_dict(value["learner"])
    scope = PilotScope.from_dict(value["scope"])
    if not isinstance(value["scope"]["max_cost_usd"], str):
        raise ValidationError("Policy handoff cost limit must be an exact decimal string.")
    compatibility = FUNCTION_COMPATIBILITY if value["schema_version"] == 2 else COMPATIBILITY
    if policy.fingerprint() != value["policy_sha256"] or learner.policy.sha256 != value["policy_sha256"] or _fingerprint(learner.to_dict()) != value["learner_content_sha256"] or value["compatibility"] != compatibility:
        raise ValidationError("Exact policy/learner/runtime contract differs from this handoff.")
    if len(scope.pilot_id) > 128 or any(marker in scope.repository_ref for marker in ("*", "?", "[", "]")):
        raise ValidationError("Policy handoff needs a bounded pilot ID and an explicit repository scope.")
    for developer in scope.developer_ids:
        if len(developer) > 64 or any(marker in developer for marker in ("*", "?", "[", "]")):
            raise ValidationError("Policy handoff developer scope must contain explicit bounded identities, not patterns.")
    if set(scope.task_types) - set(learner.plan.task_types):
        raise ValidationError("Policy handoff scope includes categories outside its exact learner validation plan.")
    for rule in policy.rules:
        model = policy.model(rule.model)
        if model is None or not model.approved or not rule.evidence_refs or rule.task_type not in model.task_types and "*" not in model.task_types:
            raise ValidationError("Policy handoff rule needs a registered approved compatible model and declared evidence.")
    for rule in learner.payload()["rules"]:
        model = policy.model(rule["recommended_model"]) if rule["recommended_model"] else None
        if model is not None and rule["task_type"] not in model.task_types and "*" not in model.task_types:
            raise ValidationError("Learned handoff rule exceeds its model's saved task capability.")
    counts = learner.counts
    if (sum(item["executions"] for item in learner.evidence) != counts["executions"]
        or counts["current_results"] + counts["pending_results"] != counts["executions"]
        or counts["model_overrides"] > counts["executions"]
        or sum(item["suggestions"] for item in learner.evidence) > counts["recommendations"]
        or sum(item["accepts"] + item["rejects"] for item in learner.evidence) > counts["responses"]):
        raise ValidationError("Learner aggregate evidence contradicts its training coverage counts.")
    from engine.delivery_contract import LocalFunctionChatEnvelope, delivery_envelope
    if not isinstance(value["model_bindings"], list):
        raise ValidationError("Model bindings must be a metadata array.")
    for row in value["model_bindings"]:
        object_fields(row, ("model_id", "envelope"), ("model_id", "envelope"))
    if [row["model_id"] for row in value["model_bindings"]] != [model.model_id for model in policy.models]:
        raise ValidationError("Model bindings must retain canonical policy registry order.")
    aliases = set()
    for row in value["model_bindings"]:
        if row["envelope"] is not None:
            envelope = delivery_envelope(row["envelope"])
            if envelope.model_id != row["model_id"] or envelope.gateway_model in aliases:
                raise ValidationError("Gateway aliases must bind exactly one policy model.")
            aliases.add(envelope.gateway_model)
            if isinstance(envelope, LocalFunctionChatEnvelope) and (value["schema_version"] != 2 or set(tool.capability for tool in envelope.local_tools) - set(policy.model(row["model_id"]).tools)):
                raise ValidationError("Local-function handoff exceeds its version or saved model capabilities.")
    if not isinstance(value["unsupported"], list):
        raise ValidationError("Unsupported handoff paths must be a metadata array.")
    unbound = {row["model_id"] for row in value["model_bindings"] if row["envelope"] is None}
    declared = set()
    for item in value["unsupported"]:
        object_fields(item, ("model_id", "reason"), ("model_id", "reason"))
        text(item["reason"], "reason")
        if item["model_id"] is not None:
            text(item["model_id"], "model_id")
            if policy.model(item["model_id"]) is None:
                raise ValidationError("Unsupported entry names a model outside the handoff registry.")
            declared.add(item["model_id"])
    if unbound - declared:
        raise ValidationError("Missing model envelopes must remain explicitly unsupported; hashes cannot hide unknown bounds.")
    return value


@transaction.atomic
def build(request, scope_ref):
    from .authorization import _reviewer, _pilot, _validate_authorization
    member = _reviewer(request)
    approval = _pilot(member, scope_ref)
    target = approval.data.get("target")
    if target not in ("live", "simulation"):
        raise ValidationError("Only stored live or simulation policy scopes support handoff.")
    saved = _validate_authorization(approval)
    review = approval.review.data
    if approval.review.company_id != member.company.pk or approval.data["review_sha256"] != review["sha256"] or review["sha256"] != _fingerprint({key: value for key, value in review.items() if key != "sha256"}):
        raise ValidationError("Policy handoff differs from its exact stored company review.")
    learner = approval.review.data["learner"]
    learned = LearnedModel.from_dict(learner)
    if target == "simulation":
        # Simulation stores its scope inside a local receipt, not a live record.
        # Reuse the reviewed policy; never manufacture live aliases or authority.
        policy, scope = learned.policy.policy, saved.data["scope"]
    else:
        policy, scope = Policy.from_dict(saved["policy"]["policy"]), saved["scope"]
    bindings, unsupported = [], []
    for model in policy.models:
        envelope = None
        if target == "simulation":
            unsupported.append({"model_id": model.model_id, "reason": "Simulation-only policy copy: no live delivery envelope or execution permission is granted."})
        else:
            try:
                envelope = envelope_for(member.company, model.model_id).to_dict()
            except ValidationError as error:
                unsupported.append({"model_id": model.model_id, "reason": str(error)})
        bindings.append({"model_id": model.model_id, "envelope": envelope})
    if policy.fingerprint() != Policy.from_dict(member.company.policy).fingerprint():
        unsupported.append({"model_id": None, "reason": "Current company policy differs; this historical scope cannot be applied."})
    if target == "live":
        from .live_authorization import live_guard
        guard = live_guard(approval, member.company, allow_future_recommendations=True)
        if guard["status"] != "current":
            unsupported.append({"model_id": None, "reason": guard["reason"]})
        runtime = ScopedSelectionRuntime.objects.filter(authorization=approval).first()
        if runtime is None or _state(runtime)["status"] != "active":
            unsupported.append({"model_id": None, "reason": "No active conditional runtime. Export cannot activate or resume one."})
    else:
        unsupported.append({"model_id": None, "reason": "This is a simulation-pilot handoff, not a live approval. Even an active simulation cannot authorize gateway delivery."})
    functions = any(row["envelope"] is not None and row["envelope"].get("schema_version") == 2 for row in bindings)
    value = {"schema_version": 2 if functions else 1, "kind": "tarkado_existing_gateway_policy", "reference_path": REFERENCE,
             "company_id": str(member.company.company_id), "deployment_id": str(member.company.deployment_id),
             "company_revision": member.company.revision, "scope_ref": str(approval.reference), "scope": scope,
             "policy": policy.to_dict(), "policy_sha256": policy.fingerprint(), "learner": learner,
             "learner_content_sha256": _fingerprint(learner), "model_bindings": bindings, "compatibility": dict(FUNCTION_COMPATIBILITY if functions else COMPATIBILITY),
             "unsupported": unsupported, "execution_credential": False, "portable_live_approval": False, "routing_enabled": False}
    value["sha256"] = _fingerprint(value)
    return validate(value)
