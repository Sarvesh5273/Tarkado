"""Explicit existing-LiteLLM startup; never reads OpenCode/provider credentials."""

import os

from engine.litellm_delivery import CompanyBackend, make_callback
from engine.schemas import ValidationError, integer, object_fields, strings, text
from engine.startup_config import private_json


def callback_from_config(path):
    value = private_json(path)
    fields = ("schema_version", "company_origin", "credential_file", "managed_aliases", "managed_deployment_ids", "timeout_seconds")
    object_fields(value, fields, fields)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValidationError("Unsupported gateway startup configuration.")
    aliases = strings(value["managed_aliases"], "managed_aliases")
    deployments = strings(value["managed_deployment_ids"], "managed_deployment_ids")
    if not aliases or not deployments:
        raise ValidationError("Explicit gateway alias/deployment lists are required.")
    timeout = integer(value["timeout_seconds"], "timeout_seconds")
    if not 1 <= timeout <= 120:
        raise ValidationError("Use a bounded explicit metadata transport timeout.")
    credential_path = text(value["credential_file"], "credential_file")
    if not os.path.isabs(credential_path):
        raise ValidationError("Select one explicit absolute private gateway credential file.")
    credential = private_json(credential_path, limit=4096)
    object_fields(credential, ("origin", "credential"), ("origin", "credential"))
    if credential["origin"] != value["company_origin"]:
        raise ValidationError("Machine credential origin differs from its explicit company startup config.")
    token = credential["credential"]
    if not isinstance(token, str) or len(token) != 43 or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for ch in token):
        raise ValidationError("Scoped machine credential has an invalid shape.")
    backend = CompanyBackend(value["company_origin"], token, timeout=timeout)
    return make_callback(backend, managed_aliases=aliases, managed_deployment_ids=deployments)


def callback_from_environment():
    path = os.environ.get("TARKADO_GATEWAY_CONFIG")
    if not path:
        raise ValidationError("Set the explicitly reviewed private TARKADO_GATEWAY_CONFIG path before loading this callback instance.")
    return callback_from_config(path)
