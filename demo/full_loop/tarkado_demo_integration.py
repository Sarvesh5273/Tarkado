"""DEMO-ONLY company integration for the Tarkado full-loop demonstration.

Loaded only through the reviewed-integration manifest of `engine company service
--load-reviewed-integration`. It is NOT a production verifier and lives outside
engine/ on purpose. It supplies:

* DemoCIReadinessVerifier: re-validates every reviewed task outcome against the
  HMAC-signed metadata records of the demo CI (demo_ci.py), pins the exact CI
  criteria fingerprint and the demo evaluation design, and persists one stable
  assessment per exact readiness request. Rechecks consult current evidence.
* DemoHostDeliveryVerifier: returns the bounded local-function envelope for the
  one reviewed cheap model, built from a host-validation record that the demo
  runner captured from the installed OpenCode tool definitions.

Settings come from one owner-only private JSON file named by
TARKADO_DEMO_INTEGRATION_CONFIG. On a single demo machine the separation between
CI, company service and developers is procedural, not cryptographic.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.company.delivery import DeliveryVerifier
from engine.company.integration import CompanyIntegration
from engine.company.readiness_gate import ReadinessAssessment, ReadinessVerifier
from engine.delivery_contract import LocalFunctionChatEnvelope, LocalFunctionTool
from engine.schemas import ValidationError
from engine.startup_config import private_json

import demo_ci

INTEGRATION_ID = "tarkado-demo-full-loop-v1"
CRITERIA_VERSION = "demo-ci-readiness-v1"
ASSESSMENT_HOURS = 12
FIELDS = ("company_id", "deployment_id", "ci_ledger_dir", "ci_key_file", "criteria_sha256", "assessment_dir",
          "host_validation_file", "min_senior_successes", "min_senior_sessions")
# DEMO prices (USD per 1M tokens) for the labelled stand-in provider. A real
# deployment takes these from its reviewed provider contract.
MODELS = {
    "company/luna": {"gateway_model": "company-cheap", "provider_model": "gpt-5.6-luna", "input_token_ceiling": 128000,
                     "output_token_ceiling": 4096, "input": "0.20", "cached": "0.02", "output": "1.20"},
}
TOOL_CAPABILITIES = {"read": "read", "glob": "read", "grep": "read", "edit": "edit", "write": "edit"}


def _config():
    path = os.environ.get("TARKADO_DEMO_INTEGRATION_CONFIG")
    if not path:
        raise ValidationError("DEMO integration config path is not set.")
    value = private_json(path)
    if not isinstance(value, dict) or set(value) != set(FIELDS):
        raise ValidationError("DEMO integration config has unexpected fields.")
    return value


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class DemoCIReadinessVerifier(ReadinessVerifier):
    def __init__(self, config):
        self.config = config
        self.key = Path(config["ci_key_file"]).read_bytes()
        if len(self.key) < 32:
            raise ValidationError("DEMO CI key is missing or too short.")

    def _check_evidence(self, request):
        from engine.company.models import Company, EvidenceReview
        from engine.company.tasks import _session_ref, company_ledger
        config = self.config
        if (request.company_id, request.deployment_id) != (config["company_id"], config["deployment_id"]):
            raise ValidationError("Readiness request names another company/deployment.")
        if demo_ci.criteria_sha256() != config["criteria_sha256"]:
            raise ValidationError("DEMO CI criteria changed since they were pinned; re-review the criteria.")
        company = Company.objects.get(company_id=request.company_id)
        review = EvidenceReview.objects.get(reference=request.review_ref, company=company)
        if review.data.get("sha256") != request.review_sha256 or review.data["report"].get("report_sha256") != request.report_sha256:
            raise ValidationError("Readiness request does not match the stored evidence review.")
        plan = review.data["learner"]["plan"]
        # Evaluation design: real team source, validation split, predeclared
        # categories/sessions, and at least the demo's evidence thresholds.
        if (plan["source_kind"] != "team" or plan["dataset_split"] != "validation"
                or plan["min_senior_successes"] < config["min_senior_successes"]
                or plan["min_senior_sessions"] < config["min_senior_sessions"]):
            raise ValidationError("Review evaluation design is below the pinned DEMO criteria.")
        ledger = company_ledger(company, "team")
        tasks = {item.recommendation_id: item.task for item in ledger.recommendations}
        results = {item.result_id: item for item in ledger.results}
        records = []
        for row in review.data["report"]["observations"]:
            if row["result_id"] is None:
                continue  # pending stays unknown; the engine already counts it as such
            result = results.get(row["result_id"])
            task = tasks.get(row["recommendation_id"])
            if result is None or task is None:
                raise ValidationError("Reviewed outcome is missing from current company evidence.")
            reference = result.evidence_ref or ""
            if not reference.startswith("ci:"):
                raise ValidationError("Every reviewed outcome must cite an independent DEMO CI record.")
            record = demo_ci.load_verified(config["ci_ledger_dir"], self.key, reference[3:])
            if record is None:
                raise ValidationError("Cited CI record is missing, revoked or fails signature verification.")
            # The ledger namespaces declared session labels per company/developer.
            session_ref = _session_ref(company, record["developer"], record["session_id"])
            if (record["criteria_sha256"] != config["criteria_sha256"] or record["task_id"] != task.task_id
                    or session_ref != task.session_id or record["developer"] != task.developer_id
                    or record["category"] != task.task_type):
                raise ValidationError("CI record does not match the reviewed task identity/criteria.")
            if result.desired_result is True and record["passed"] is not True:
                raise ValidationError("A reported success contradicts its independent CI record.")
            if result.tests_passed is not None and result.tests_passed != record["tests_passed"]:
                raise ValidationError("Reported test status contradicts its independent CI record.")
            records.append(record["record_id"])
        if not records:
            raise ValidationError("No independently checked outcomes exist in this review.")
        return sorted(records)

    def verify(self, request):
        records = self._check_evidence(request)
        directory = Path(self.config["assessment_dir"])
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / f"{request.sha256}.json"
        if path.exists():
            assessment = ReadinessAssessment.from_dict(json.loads(path.read_text()))
            if assessment.request_sha256 != request.sha256:
                raise ValidationError("Stored DEMO assessment is inconsistent.")
            return assessment
        verified = _now()
        assessment = ReadinessAssessment(
            verifier_id=INTEGRATION_ID,
            evidence_ref="demo-ci-readiness:" + _sha({"records": records, "criteria": self.config["criteria_sha256"]}),
            criteria_version=CRITERIA_VERSION, request_sha256=request.sha256,
            verified_at=verified.isoformat(), valid_until=(verified + timedelta(hours=ASSESSMENT_HOURS)).isoformat(),
            outcomes_verified=True, evaluation_design_verified=True, criteria_validated=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(assessment.to_dict(), stream, sort_keys=True)
        return assessment


class DemoHostDeliveryVerifier(DeliveryVerifier):
    def __init__(self, config):
        self.config = config

    def envelope(self, company_id, deployment_id, model_id):
        if (company_id, deployment_id) != (self.config["company_id"], self.config["deployment_id"]):
            raise ValidationError("Delivery request names another company/deployment.")
        model = MODELS.get(model_id)
        if model is None:
            raise ValidationError("No DEMO host/billing envelope exists for this model.")
        host = private_json(self.config["host_validation_file"])
        if host.get("gateway_model") != model["gateway_model"] or host.get("record") != "demo-host-validation-v1":
            raise ValidationError("DEMO host validation record does not cover this gateway model.")
        tools = tuple(LocalFunctionTool(name=name, capability=TOOL_CAPABILITIES[name], function_sha256=digest)
                      for name, digest in sorted(host["tools"].items()) if name in TOOL_CAPABILITIES)
        if {tool.name for tool in tools} != set(TOOL_CAPABILITIES):
            raise ValidationError("DEMO host validation did not capture every reviewed local tool.")
        reference = "demo-host-validation:" + _sha(host)
        return LocalFunctionChatEnvelope(
            model_id=model_id, gateway_model=model["gateway_model"], provider_model=model["provider_model"],
            input_token_ceiling=model["input_token_ceiling"], output_token_ceiling=model["output_token_ceiling"],
            input_usd_per_million=model["input"], cached_input_usd_per_million=model["cached"],
            output_usd_per_million=model["output"], fixed_attempt_usd="0", evidence_ref=reference,
            valid_until=host["valid_until"], verified_at=host["verified_at"], local_tools=tools,
            local_execution_evidence_ref="demo-opencode-permissions:" + host["permissions_sha256"])


def create():
    config = _config()
    return CompanyIntegration(company_id=config["company_id"], deployment_id=config["deployment_id"],
                              integration_id=INTEGRATION_ID, readiness=DemoCIReadinessVerifier(config),
                              delivery=DemoHostDeliveryVerifier(config), billing=None)
