"""LiteLLM physical-attempt callbacks, not a replacement gateway or provider client.

Importing this module loads no plugin and contacts nothing. Explicit registration
and installed-runtime validation need operator approval. Core is dependency-free;
the optional factory imports the company's existing LiteLLM installation only.
"""

import asyncio
import copy
import inspect
import time
import uuid
from importlib.metadata import version
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from engine.delivery_contract import TextChatEnvelope, chat_request, chat_usage
from engine.importers import parse_json
from engine.schemas import ValidationError, object_fields
from engine.privacy import PrivacyError, ensure_safe


CANDIDATE_LITELLM_VERSION = "1.104.0"
CONTEXT_KEY = "tarkado_delivery_v1"
META_FIELDS = ("tarkado_binding", "tarkado_task", "tarkado_session", "tarkado_request", "tarkado_kind")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValidationError("Policy metadata transport refused a redirect.")


class CompanyBackend:
    """Sends ONLY approved metadata to Tarkado, never inference content."""

    def __init__(self, origin, gateway_token, timeout=10, loopback=False):
        parsed = urlsplit(origin)
        if (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")
            or parsed.scheme != "https" and not (loopback and parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "::1"))):
            raise ValidationError("Use an exact company HTTPS origin (or explicitly approved test loopback).")
        self.origin, self.token, self.timeout = origin.rstrip("/"), gateway_token, timeout
        self.opener = build_opener(NoRedirect())

    def call(self, operation, value):
        import json
        if operation not in ("describe", "begin", "attempt", "settle", "close"):
            raise ValidationError("Unsupported machine metadata operation.")
        request = Request(self.origin + "/api/delivery/v1/" + operation + "/", json.dumps(value).encode(),
                          {"Content-Type": "application/json", "Authorization": "Bearer " + self.token}, method="POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read(65537)
                if len(body) > 65536:
                    raise ValidationError("Policy metadata reply exceeded its bound.")
                return parse_json(body.decode())
        except Exception:
            # Never print URLs, request data, credentials, or gateway error bodies.
            raise ValidationError("Policy metadata service refused or is unavailable; retain outstanding obligations.") from None


class AttemptHooks:
    def __init__(self, backend, buffer_streams=False):
        self.backend = backend
        self.buffer_streams = buffer_streams

    def pre_call(self, data, authenticated_user):
        runtime_metadata = data.get("metadata")
        if not isinstance(runtime_metadata, dict) or not set(META_FIELDS).issubset(runtime_metadata):
            raise ValidationError("Missing exact Tarkado task/request metadata.")
        metadata = {key: runtime_metadata[key] for key in META_FIELDS}
        user_ref = getattr(authenticated_user, "user_id", None)
        if not isinstance(user_ref, str) or not user_ref:
            raise ValidationError("LiteLLM must supply its authenticated mapped user, not a request user/header label.")
        context = {"binding_ref": metadata["tarkado_binding"], "task_token": metadata["tarkado_task"],
                   "session_ref": metadata["tarkado_session"], "gateway_user_ref": user_ref}
        envelope = TextChatEnvelope.from_dict(self.backend.call("describe", context)["envelope"])
        # The pinned proxy adds transport/tracing metadata before call hooks.
        # These do not become provider settings or enter company records.
        runtime_keys = ("proxy_server_request", "litellm_call_id", "litellm_trace_id", "litellm_session_id")
        shape = chat_request({key: value for key, value in data.items() if key not in runtime_keys}, envelope)
        opened = {**context, "request_id": metadata["tarkado_request"], "kind": metadata["tarkado_kind"], **shape}
        self.backend.call("begin", opened)
        result = dict(data)
        # Do not send task tokens/identity metadata to the model provider.
        context = {**opened, "envelope": envelope.to_dict()}
        # LiteLLM's function_setup consumes top-level metadata as its own
        # logging/runtime metadata; the physical hook removes it before lowering.
        result["metadata"] = {CONTEXT_KEY: context}
        result["litellm_params"] = {"metadata": {CONTEXT_KEY: context}}
        return result

    def pre_attempt(self, kwargs):
        context = self._context(kwargs)
        envelope = TextChatEnvelope.from_dict(context["envelope"])
        shape = chat_request(kwargs, envelope, physical=True)
        if kwargs.get("api_base") not in (None, "https://api.openai.com/v1") or kwargs.get("custom_llm_provider") not in (None, "openai"):
            raise ValidationError("Unapproved provider endpoint/transport differs from the OpenAI binding.")
        if kwargs.get("caching") not in (None, False):
            raise ValidationError("Caching has no supported physical-attempt settlement contract.")
        if kwargs.get("client") is not None and getattr(kwargs["client"], "max_retries", None) != 0:
            raise ValidationError("Provider client has unobserved internal retries; disable them before admission.")
        attempt_id = str(uuid.uuid4())
        payload = {key: context[key] for key in ("task_token", "binding_ref", "session_ref", "request_id")}
        self.backend.call("attempt", {**payload, "attempt_id": attempt_id, "provider_model": envelope.provider_model, **shape})
        result = dict(kwargs)
        result.pop("metadata", None)
        # SDK-internal retries cannot bypass the physical-attempt callback.
        # The approved deployment must also validate provider lowering honors it.
        result["max_retries"] = 0
        if self.buffer_streams and shape["stream"]:
            result["stream"] = False
            result.pop("stream_options", None)
        params = dict(result["litellm_params"])
        metadata = dict(params["metadata"])
        # Each retry gets an independent attempt context; no shared mutable token.
        metadata[CONTEXT_KEY] = {**context, "attempt_id": attempt_id, "started": time.monotonic()}
        params["metadata"] = metadata
        result["litellm_params"] = params
        return result

    def _context(self, kwargs):
        context = kwargs.get("metadata", {}).get(CONTEXT_KEY) or kwargs.get("litellm_params", {}).get("metadata", {}).get(CONTEXT_KEY)
        if not isinstance(context, dict):
            raise ValidationError("Missing exact logical admission context; physical provider execution is refused.")
        return copy.deepcopy(context)

    def settle(self, kwargs, response=None, failed=False):
        context = self._context(kwargs)
        if "attempt_id" not in context:
            # Pre-admission refusal never creates a free or chargeable fake attempt.
            return
        envelope = TextChatEnvelope.from_dict(context["envelope"])
        usage = None
        model = response.get("model") if isinstance(response, dict) else getattr(response, "model", None)
        try:
            if model is not None: ensure_safe(model)
        except PrivacyError:
            model = None
        if not failed and response is not None:
            tier = response.get("service_tier", "default") if isinstance(response, dict) else getattr(response, "service_tier", "default")
            if model == envelope.provider_model and tier in (None, "default"):
                try:
                    usage = chat_usage(response)
                    if usage is not None:
                        envelope.cost(usage)
                except ValidationError:
                    usage = None
        known = usage is not None
        payload = {"binding_ref": context["binding_ref"], "attempt_id": context["attempt_id"],
                   "cost_usd": str(envelope.cost(usage)) if known else None, "usage": usage,
                   "outcome": "completed" if known else "unknown", "latency_ms": int(max(0, time.monotonic() - context["started"]) * 1000),
                   "evidence_ref": "reviewed-chat-usage:" + context["attempt_id"] if known else None, "actual_model": model}
        self.backend.call("settle", payload)

    async def stream(self, kwargs, response):
        final, exhausted = None, False
        envelope = TextChatEnvelope.from_dict(self._context(kwargs)["envelope"])
        wrong_model = False
        try:
            async for chunk in response:
                # Only model/usage are projected. Never inspect choices or text.
                usage = chunk.get("usage") if isinstance(chunk, dict) else getattr(chunk, "usage", None)
                model = chunk.get("model") if isinstance(chunk, dict) else getattr(chunk, "model", None)
                wrong_model = wrong_model or model != envelope.provider_model
                if usage is not None:
                    try:
                        projected = chat_usage(chunk)
                    except ValidationError:
                        projected = None
                    tier = chunk.get("service_tier", "default") if isinstance(chunk, dict) else getattr(chunk, "service_tier", "default")
                    final = None if projected is None else {"model": model, "service_tier": tier, "usage": {
                        "prompt_tokens": projected["input_tokens"], "completion_tokens": projected["output_tokens"],
                        "prompt_tokens_details": {"cached_tokens": projected["cached_input_tokens"]},
                        "completion_tokens_details": {"reasoning_tokens": projected["reasoning_tokens"]}}}
                yield chunk
            exhausted = True
        finally:
            # Cancellation/timeout is not zero. Backend outage leaves the original
            # reservation untouched and the next attempt cannot reuse it.
            await asyncio.to_thread(self.settle, kwargs, final if exhausted and not wrong_model else None, not exhausted or wrong_model)


def make_callback(backend, *, managed_aliases, managed_deployment_ids):
    """Explicit optional host registration; not called by either shipped launcher."""
    if not managed_aliases or not managed_deployment_ids or any(not isinstance(value, str) or not value for value in (*managed_aliases, *managed_deployment_ids)):
        raise ValidationError("Explicit reviewed gateway aliases and deployment IDs are required; do not intercept unrelated gateway work.")
    aliases, deployments = frozenset(managed_aliases), frozenset(managed_deployment_ids)
    if version("litellm") != CANDIDATE_LITELLM_VERSION:
        raise ValidationError("Unsupported LiteLLM version; validate a new callback contract before registration.")
    from litellm.integrations.custom_logger import CustomLogger
    expected = {
        "async_pre_call_deployment_hook": ("self", "kwargs", "call_type"),
        "async_post_call_success_deployment_hook": ("self", "request_data", "response", "call_type"),
        "async_post_call_failure_deployment_hook": ("self", "request_data", "exception", "call_type", "fallback_depth"),
    }
    for name, fields in expected.items():
        method = getattr(CustomLogger, name, None)
        if method is None or tuple(inspect.signature(method).parameters) != fields:
            raise ValidationError("Installed LiteLLM callback signature differs; do not load a silent non-enforcing hook.")
    from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper
    from litellm.llms.base_llm.base_model_iterator import MockResponseIterator
    hooks = AttemptHooks(backend, buffer_streams=True)

    def has_context(data):
        return CONTEXT_KEY in (data.get("metadata") or {}) or CONTEXT_KEY in data.get("litellm_params", {}).get("metadata", {})

    def managed_request(data):
        metadata = data.get("metadata") or {}
        return data.get("model") in aliases or any(key in metadata for key in META_FIELDS) or has_context(data)

    def managed_attempt(data):
        if has_context(data):
            return True
        model_info = data.get("model_info") or (data.get("metadata") or {}).get("model_info") or {}
        deployment_id = model_info.get("id")
        if not deployment_id:
            raise ValidationError("Physical deployment identity is unknown; bounded delivery cannot assume an unrelated path.")
        return deployment_id in deployments

    class TarkadoCallback(CustomLogger):
        def __init__(self):
            super().__init__(turn_off_message_logging=True)

        async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
            if not managed_request(data):
                return data
            if getattr(call_type, "value", call_type) not in ("completion", "acompletion"):
                raise ValidationError("Only reviewed text chat completion is supported.")
            return await asyncio.to_thread(hooks.pre_call, data, user_api_key_dict)

        async def async_pre_call_deployment_hook(self, kwargs, call_type):
            if not managed_attempt(kwargs):
                return kwargs
            if getattr(call_type, "value", call_type) not in ("completion", "acompletion"):
                raise ValidationError("Unsupported physical provider call type.")
            return await asyncio.to_thread(hooks.pre_attempt, kwargs)

        async def async_post_call_success_deployment_hook(self, request_data, response, call_type):
            if not has_context(request_data):
                return response
            if isinstance(response, CustomStreamWrapper):
                return response
            await asyncio.to_thread(hooks.settle, request_data, response)
            if hooks._context(request_data)["stream"]:
                # The pinned wrapper bypasses success hooks for actual provider
                # streams. Make one bounded NON-streaming paid call, then use
                # LiteLLM's own buffered-response iterator for the client stream.
                # This delays the first client chunk, never makes another call,
                # and never fabricates a provider response or usage.
                logging_obj = request_data["litellm_logging_obj"]
                logging_obj.stream = True
                return CustomStreamWrapper(completion_stream=MockResponseIterator(response), model=response.model,
                    logging_obj=logging_obj, custom_llm_provider="openai", stream_options={"include_usage": True})
            return response

        async def async_post_call_failure_deployment_hook(self, request_data, exception, call_type, fallback_depth=None):
            if not has_context(request_data):
                return
            # Never retain exception messages/tracebacks or infer a free retry.
            await asyncio.to_thread(hooks.settle, request_data, None, True)

    return TarkadoCallback()
