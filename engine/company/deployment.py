"""A single-host HTTPS-proxy deployment contract, never a public development server."""

from pathlib import Path
import re
from urllib.parse import urlsplit

from engine.importers import parse_json
from engine.schemas import ValidationError, boolean, object_fields, text


def validate_deployment(value):
    fields = ("public_origin", "https_proxy_configured", "private_single_host", "backup_policy", "operator_contact")
    data = object_fields(value, fields, fields)
    origin = text(data["public_origin"], "public_origin")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise ValidationError("Company serving requires an exact HTTPS origin without credentials, path, query, or wildcard.")
    if "*" in parsed.netloc or parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        raise ValidationError("Company serving requires an explicit company HTTPS host, not development/wildcard hosts.")
    try:
        port = parsed.port
    except ValueError:
        raise ValidationError("Company HTTPS origin has an invalid port.") from None
    if port is not None and not 1 <= port <= 65535:
        raise ValidationError("Company HTTPS origin has an invalid port.")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", parsed.hostname):
        raise ValidationError("Use an explicit lowercase DNS company host for this supported deployment.")
    if not boolean(data["https_proxy_configured"], "https_proxy_configured") or not boolean(data["private_single_host"], "private_single_host"):
        raise ValidationError("An operator-configured HTTPS proxy and private single-host state are required.")
    text(data["backup_policy"], "backup_policy")
    text(data["operator_contact"], "operator_contact")
    return {**data, "host": parsed.hostname, "origin": origin}


def load_deployment(path):
    from .runtime import check_private_file
    path = Path(path)
    check_private_file(path)
    return validate_deployment(parse_json(path.read_text(encoding="utf-8")))


def serve(directory, configuration):
    from django.conf import settings
    from django.core.wsgi import get_wsgi_application
    from waitress import serve as waitress_serve
    configuration = validate_deployment({key: value for key, value in configuration.items() if key not in ("host", "origin")})
    if settings.TARKADO_SERVICE_MODE != "company_https_proxy" or settings.TARKADO_PUBLIC_ORIGIN != configuration["origin"]:
        raise ValidationError("Company serving requires the matching hardened HTTPS configuration, not development settings.")
    socket = Path(directory).absolute() / "company.sock"
    if socket.exists() or socket.is_symlink():
        raise ValidationError("Server socket already exists; check the existing process before changing an operator-owned socket.")
    # A private Unix socket limits transport to local operator/proxy access. The
    # proxy must overwrite the proto header; client-supplied identity is never trusted.
    waitress_serve(get_wsgi_application(), unix_socket=str(socket), unix_socket_perms="600", threads=4,
                  trusted_proxy="localhost", trusted_proxy_count=1, trusted_proxy_headers={"x-forwarded-proto"},
                  clear_untrusted_proxy_headers=True, expose_tracebacks=False, ident="Tarkado",
                  max_request_body_size=131072, max_request_header_size=16384,
                  inbuf_overflow=262144, outbuf_overflow=1048576, channel_request_lookahead=0,
                  connection_limit=32, channel_timeout=30)
