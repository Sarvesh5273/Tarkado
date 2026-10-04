"""Versioned policy handoff, never a portable approval or execution credential."""

from django.db import transaction

from engine.feedback import _fingerprint
from engine.schemas import Policy, ValidationError, object_fields
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


def validate(value):
    object_fields(value, FIELDS, FIELDS)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "tarkado_existing_gateway_policy" or value["reference_path"] != REFERENCE:
        raise ValidationError("Unsupported versioned gateway policy handoff.")
    if value["execution_credential"] is not False or value["portable_live_approval"] is not False or value["routing_enabled"] is not False:
        raise ValidationError("A policy handoff cannot contain portable live authority or execution permission.")
    if value["sha256"] != _fingerprint({key: val for key, val in value.items() if key != "sha256"}):
        raise ValidationError("Policy handoff content changed.")
    policy = Policy.from_dict(value["policy"])
    if policy.fingerprint() != value["policy_sha256"] or _fingerprint(value["learner"]) != value["learner_content_sha256"] or value["compatibility"] != COMPATIBILITY:
        raise ValidationError("Exact policy/learner/runtime contract differs from this handoff.")
    from engine.delivery_contract import TextChatEnvelope
    if not isinstance(value["model_bindings"], list) or [row.get("model_id") for row in value["model_bindings"]] != [model.model_id for model in policy.models]:
        raise ValidationError("Model bindings must retain canonical policy registry order.")
    aliases = set()
    for row in value["model_bindings"]:
        object_fields(row, ("model_id", "envelope"), ("model_id", "envelope"))
        if row["envelope"] is not None:
            envelope = TextChatEnvelope.from_dict(row["envelope"])
            if envelope.model_id != row["model_id"] or envelope.gateway_model in aliases:
                raise ValidationError("Gateway aliases must bind exactly one policy model.")
            aliases.add(envelope.gateway_model)
    return value


@transaction.atomic
def build(request, scope_ref):
    from .authorization import _reviewer, _pilot
    member = _reviewer(request)
    approval = _pilot(member, scope_ref)
    policy = Policy.from_dict(approval.data["policy"]["policy"])
    learner = approval.review.data["learner"]
    bindings, unsupported = [], []
    for model in policy.models:
        envelope = None
        try:
            envelope = envelope_for(member.company, model.model_id).to_dict()
        except ValidationError as error:
            unsupported.append({"model_id": model.model_id, "reason": str(error)})
        bindings.append({"model_id": model.model_id, "envelope": envelope})
    if policy.fingerprint() != Policy.from_dict(member.company.policy).fingerprint():
        unsupported.append({"model_id": None, "reason": "Current company policy differs; this historical scope cannot be applied."})
    if approval.data.get("target") == "live":
        from .live_authorization import live_guard
        guard = live_guard(approval, member.company, allow_future_recommendations=True)
        if guard["status"] != "current":
            unsupported.append({"model_id": None, "reason": guard["reason"]})
    runtime = ScopedSelectionRuntime.objects.filter(authorization=approval).first()
    if runtime is None or _state(runtime)["status"] != "active":
        unsupported.append({"model_id": None, "reason": "No active conditional runtime. Export cannot activate or resume one."})
    value = {"schema_version": 1, "kind": "tarkado_existing_gateway_policy", "reference_path": REFERENCE,
             "company_id": str(member.company.company_id), "deployment_id": str(member.company.deployment_id),
             "company_revision": member.company.revision, "scope_ref": str(approval.reference), "scope": approval.data["scope"],
             "policy": policy.to_dict(), "policy_sha256": policy.fingerprint(), "learner": learner,
             "learner_content_sha256": _fingerprint(learner), "model_bindings": bindings, "compatibility": dict(COMPATIBILITY),
             "unsupported": unsupported, "execution_credential": False, "portable_live_approval": False, "routing_enabled": False}
    value["sha256"] = _fingerprint(value)
    return validate(value)
