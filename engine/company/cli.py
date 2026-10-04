"""Optional company commands, imported lazily to preserve the offline CLI."""

import getpass
import json
import sys
from pathlib import Path


def add_commands(commands):
    company = commands.add_parser("company", help="Invitation-only company setup and real local login; live routing is unavailable")
    actions = company.add_subparsers(dest="company_action", required=True)
    bootstrap = actions.add_parser("bootstrap", help="Explicitly enroll the first administrator in a new private store")
    bootstrap.add_argument("--store", type=Path, default=Path("local/company"))
    bootstrap.add_argument("--name", required=True)
    bootstrap.add_argument("--username", required=True)
    bootstrap.add_argument("--policy", type=Path, required=True)
    bootstrap.add_argument("--repositories", nargs="+", required=True)
    bootstrap.add_argument("--company-api", action="store_true", required=True)
    bootstrap.add_argument("--pilot-approver", action="store_true", help="Explicitly designate this administrator; never enables routing")
    for action in ("serve", "status", "upgrade"):
        help_text = {
            "serve": "Start an existing installation locally; use bootstrap first for a new store",
            "status": "Inspect an already initialized private company store",
            "upgrade": "Apply shipped migrations to an existing installation; does not create the first administrator",
        }[action]
        operation = actions.add_parser(action, help=help_text, description=help_text)
        operation.add_argument("--store", type=Path, default=Path("local/company"))
        if action == "serve":
            operation.add_argument("--port", type=int, default=8000, help="Loopback-only development port; not a production server")
    service = actions.add_parser("service", help="Company single-host server behind an operator-configured HTTPS proxy; never uses runserver")
    service.add_argument("--store", type=Path, required=True)
    service.add_argument("--deployment", type=Path, required=True, help="Private reviewed deployment configuration JSON")
    service.add_argument("--integration-manifest", type=Path, help="Private manifest binding explicit reviewed verifier factory source to this company")
    service.add_argument("--load-reviewed-integration", action="store_true", help="Explicit operator permission to execute that reviewed startup module; not pilot/evidence approval")
    backup = actions.add_parser("backup", help="Operator-requested private paired database/key backup; never overwrite")
    backup.add_argument("--store", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)


def run_command(args):
    if sys.version_info < (3, 12):
        raise ValueError("The company application requires supported Python 3.12 or later; the offline engine is independent.")
    try:
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.core.management import call_command
        from django.db import DatabaseError
    except ImportError:
        raise ValueError("Install the approved requirements-company.txt in the supported .venv before using company commands.") from None
    from engine.importers import load_policy
    from engine.privacy import redact_text
    from .runtime import configure, initialize_store

    try:
        if args.company_action == "bootstrap":
            # Validate public policy inputs before creating any account state.
            from engine.schemas import text
            policy = load_policy(args.policy)
            text(args.name, "company_name")
            for repository in args.repositories:
                text(repository, "repository_ref")
            password = getpass.getpass("First administrator password (minimum 15 characters): ")
            repeated = getpass.getpass("Repeat password: ")
            if password != repeated:
                raise ValueError("The passwords do not match; no administrator was enrolled.")
            configure(args.store, create=True)
            from django.contrib.auth import get_user_model
            from django.contrib.auth.password_validation import validate_password
            from .services import COLLECTION_FIELDS, bootstrap_company, validate_configuration, validate_username
            validate_username(args.username)
            validate_configuration(args.name, policy.to_dict(), args.repositories, list(COLLECTION_FIELDS), args.company_api)
            validate_password(password, user=get_user_model()(username=args.username))
            initialize_store(args.store)
            call_command("migrate", interactive=False, verbosity=0)
            company = bootstrap_company(args.username, password, args.name, policy.to_dict(), args.repositories, args.pilot_approver)
        else:
            deployment = None
            if args.company_action == "service":
                from .deployment import load_deployment
                deployment = load_deployment(args.deployment)
            configure(args.store, deployment=deployment)
            from .models import Company
            company = Company.objects.get(pk=1)
            if args.company_action == "upgrade":
                # Apply shipped additive migrations only; never reset/fake/reverse user state.
                call_command("migrate", interactive=False, verbosity=0)
        if args.company_action == "backup":
            from .backup import backup_store
            destination = backup_store(args.output)
            print(json.dumps({"backup_directory": str(destination), "includes_private_credentials": True,
                              "encrypted": False, "deployment_authorized": False}))
            return 0
        if args.company_action == "service":
            from django.db import connection
            from django.db.migrations.executor import MigrationExecutor
            executor = MigrationExecutor(connection)
            if executor.migration_plan(executor.loader.graph.leaf_nodes()):
                raise ValueError("Apply company upgrade with the server stopped before starting the company service.")
            manifest = getattr(args, "integration_manifest", None)
            approved = getattr(args, "load_reviewed_integration", False)
            if bool(manifest) != approved:
                raise ValueError("A reviewed integration manifest and explicit code-loading approval must be supplied together; default startup stays refusing.")
            if manifest:
                from .integration import load_reviewed
                loaded = load_reviewed(manifest, company, operator_approved=approved)
                print(json.dumps(loaded))
            from .deployment import serve
            print("Tarkado company service: private Unix socket; HTTPS proxy required. Live routing remains unauthorized.")
            serve(args.store, deployment)
            return 0
        if args.company_action == "serve":
            if not 1024 <= args.port <= 65535:
                raise ValueError("Choose an unprivileged port between 1024 and 65535.")
            print("Tarkado company login: loopback development only. No OpenCode access or model requests; live routing is unavailable.")
            call_command("runserver", "127.0.0.1:" + str(args.port), use_reloader=False)
            return 0
        from engine.schemas import Policy
        from django.conf import settings
        from .readiness_gate import ReadinessVerifier
        from .admission_gate import AdmissionVerifier
        from .models import Membership
        output = {"company_id": str(company.company_id), "deployment_id": str(company.deployment_id),
                  "name": company.name, "revision": company.revision, "accounts": Membership.objects.count(),
                  "login_mechanism": "django_individual_accounts", "privileged_mfa": "authenticator_required",
                  "policy_sha256": Policy.from_dict(company.policy).fingerprint(),
                   "retention_policy": "manual", "supported_runtime": "loopback_development",
                    "live_scope_approval_supported": True,
                    "connector_api_supported": True,
                    "connector_private_session_validation": False,
                    "versioned_learning_publication_supported": True,
                    "conditional_selection_supported": True,
                    "trusted_admission_verifier_configured": isinstance(settings.TARKADO_ADMISSION_VERIFIER, AdmissionVerifier),
                   "trusted_readiness_verifier_configured": isinstance(settings.TARKADO_READINESS_VERIFIER, ReadinessVerifier),
                   "routing_enabled": False, "deployment_authorized": False,
                   "note": "Company authorization mechanics support separate live scope approvals with server-verified readiness. The default verifier denies approval; scope records never enable model execution. Real evidence, the task/provider adapter, and reviewed deployment remain separate gates."}
        print(json.dumps(output, indent=2))
        return 0
    except (DjangoValidationError, DatabaseError) as error:
        print("Tarkado: company account/state operation failed: " + redact_text(str(error)), file=sys.stderr)
        return 2
