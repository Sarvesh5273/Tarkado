"""Text and bounded local-function chat contracts. No provider transport or production prices."""

from dataclasses import dataclass
from decimal import Decimal, localcontext
import hashlib
import json
import re

from engine.feedback import _fingerprint, _timestamp
from engine.pilot import _money_total
from engine.schemas import ValidationError, integer, number, object_fields, text


REQUEST_KINDS = ("primary", "title", "compaction", "generate")
USAGE_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")


def product(rate, count):
    # Preserve tiny prices as well as large counts without display rounding.
    rate = number(rate, "rate")
    with localcontext() as context:
        context.prec = max(28, len(rate.as_tuple().digits) + len(str(count)) + 8)
        return rate * count / Decimal(1000000)


@dataclass(frozen=True)
class TextChatEnvelope:
    model_id: str
    gateway_model: str
    provider_model: str
    input_token_ceiling: int
    output_token_ceiling: int
    input_usd_per_million: str
    cached_input_usd_per_million: str
    output_usd_per_million: str
    fixed_attempt_usd: str
    evidence_ref: str
    valid_until: str
    verified_at: str

    def to_dict(self):
        data = {key: getattr(self, key) for key in TextChatEnvelope.__dataclass_fields__}
        for key in ("model_id", "gateway_model", "provider_model", "evidence_ref"):
            text(data[key], key)
        for key in ("input_token_ceiling", "output_token_ceiling"):
            if integer(data[key], key) == 0:
                raise ValidationError("A reviewed positive provider token ceiling is required.")
        for key in ("input_usd_per_million", "cached_input_usd_per_million", "output_usd_per_million", "fixed_attempt_usd"):
            if not isinstance(data[key], str):
                raise ValidationError("Billing rates must be exact decimal strings, never floats.")
            number(data[key], key)
        _timestamp(self.valid_until)
        if _timestamp(self.valid_until) <= _timestamp(self.verified_at):
            raise ValidationError("Host/billing evidence has no positive verified validity interval.")
        _fingerprint(data)
        return data

    @classmethod
    def from_dict(cls, value):
        fields = tuple(cls.__dataclass_fields__)
        result = cls(**object_fields(value, fields, fields))
        result.to_dict()
        return result

    @property
    def sha256(self):
        return _fingerprint(self.to_dict())

    def maximum(self, output_limit):
        if not 0 < integer(output_limit, "output_limit") <= self.output_token_ceiling:
            raise ValidationError("Requested output limit is outside the reviewed billing envelope.")
        # Reserve the FULL reviewed billable-input ceiling, not a guessed token count.
        # This is deliberately expensive. The deployment verifier must establish
        # rejection above this ceiling, output/reasoning enforcement, and all charges.
        rate = max(number(self.input_usd_per_million, "rate"), number(self.cached_input_usd_per_million, "rate"))
        return _money_total([product(rate, self.input_token_ceiling), product(self.output_usd_per_million, output_limit),
                             number(self.fixed_attempt_usd, "fixed_attempt_usd")])

    def cost(self, usage):
        object_fields(usage, USAGE_FIELDS, USAGE_FIELDS)
        for key in USAGE_FIELDS:
            integer(usage[key], key)
        if usage["cached_input_tokens"] > usage["input_tokens"] or usage["reasoning_tokens"] > usage["output_tokens"]:
            raise ValidationError("Usage subsets contradict their total billable token counts.")
        return _money_total([product(self.input_usd_per_million, usage["input_tokens"] - usage["cached_input_tokens"]),
                             product(self.cached_input_usd_per_million, usage["cached_input_tokens"]),
                             product(self.output_usd_per_million, usage["output_tokens"]), number(self.fixed_attempt_usd, "fixed_attempt_usd")])


@dataclass(frozen=True)
class LocalFunctionTool:
    name: str
    capability: str
    function_sha256: str
    status_metadata_key: str | None = None

    def to_dict(self):
        if not isinstance(self.name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.name):
            raise ValidationError("A local function needs an exact bounded tool name.")
        if self.name in ("shell", "bash", "subagent", "execute", "batch", "webfetch", "websearch", "skill") or self.name.startswith("mcp"):
            raise ValidationError("Unrestricted shell, remote/paid tools and subagents have no supported local billing boundary.")
        if self.capability not in ("read", "edit", "test"):
            raise ValidationError("Only explicit local read/edit/test capabilities are supported.")
        builtin = {"read": "read", "glob": "read", "grep": "read", "edit": "edit", "write": "edit", "patch": "edit"}
        if self.name in builtin and self.capability != builtin[self.name]:
            raise ValidationError("Built-in tool names cannot be relabelled to broaden a task capability.")
        if not isinstance(self.function_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.function_sha256):
            raise ValidationError("Independently reviewed exact function definition fingerprint is required.")
        result = {"name": self.name, "capability": self.capability, "function_sha256": self.function_sha256}
        if self.status_metadata_key is not None:
            if self.status_metadata_key != "tarkado_status_v1":
                raise ValidationError("Only the reviewed v1 negative-status metadata contract is supported.")
            result["status_metadata_key"] = self.status_metadata_key
        return result

    @classmethod
    def from_dict(cls, value):
        fields = tuple(cls.__dataclass_fields__)
        tool = cls(**object_fields(value, fields, fields[:3]))
        tool.to_dict()
        return tool


@dataclass(frozen=True)
class LocalFunctionChatEnvelope(TextChatEnvelope):
    local_tools: tuple
    local_execution_evidence_ref: str

    def to_dict(self):
        data = TextChatEnvelope.to_dict(self)
        if not isinstance(self.local_tools, tuple) or any(not isinstance(tool, LocalFunctionTool) for tool in self.local_tools):
            raise ValidationError("Local function contract must contain immutable typed tools.")
        tools = [tool.to_dict() for tool in self.local_tools]
        if len({tool["name"] for tool in tools}) != len(tools):
            raise ValidationError("Local function names cannot bind two definitions/capabilities.")
        text(self.local_execution_evidence_ref, "local_execution_evidence_ref")
        return {**data, "schema_version": 2, "record_type": "bounded_local_function_chat",
                "local_tools": tools, "local_execution_evidence_ref": self.local_execution_evidence_ref}

    @classmethod
    def from_dict(cls, value):
        base = tuple(TextChatEnvelope.__dataclass_fields__)
        fields = base + ("schema_version", "record_type", "local_tools", "local_execution_evidence_ref")
        data = object_fields(value, fields, fields)
        if type(data["schema_version"]) is not int or data["schema_version"] != 2 or data["record_type"] != "bounded_local_function_chat" or not isinstance(data["local_tools"], list):
            raise ValidationError("Unsupported local-function envelope version or tool list.")
        result = cls(**{key: data[key] for key in base}, local_tools=tuple(LocalFunctionTool.from_dict(tool) for tool in data["local_tools"]),
                     local_execution_evidence_ref=data["local_execution_evidence_ref"])
        result.to_dict()
        return result


def delivery_envelope(value):
    if isinstance(value, dict) and "schema_version" in value:
        return LocalFunctionChatEnvelope.from_dict(value)
    return TextChatEnvelope.from_dict(value)


def bind_tools(envelope, required_tools):
    """Restrict this task to declared capabilities; do not broaden old text-only scopes."""
    if not isinstance(envelope, LocalFunctionChatEnvelope):
        if required_tools:
            raise ValidationError("Legacy text-only envelope cannot admit tool-required work.")
        return envelope
    if set(required_tools) - {tool.capability for tool in envelope.local_tools}:
        raise ValidationError("Task needs local tool capabilities not evidenced by this model/deployment envelope.")
    from dataclasses import replace
    return replace(envelope, local_tools=tuple(tool for tool in envelope.local_tools if tool.capability in required_tools))


def function_fingerprint(definition):
    """Use only inside the authorized client/gateway. Never retain the definition."""
    try:
        encoded = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError):
        raise ValidationError("Function definition is not supported canonical JSON.") from None
    return hashlib.sha256(encoded).hexdigest()


def chat_request(data, envelope, physical=False):
    """Inspect inference data only inside the authorized gateway; return metadata only."""
    allowed = ("model", "messages", "max_completion_tokens", "stream", "stream_options", "n", "store", "metadata", "service_tier")
    local = isinstance(envelope, LocalFunctionChatEnvelope)
    if local:
        allowed += ("tools", "tool_choice", "parallel_tool_calls", "temperature", "top_p", "stop")
    # These are gateway runtime fields, not accepted extra provider/body settings.
    internal = ("litellm_params", "proxy_server_request", "litellm_call_id", "custom_llm_provider", "api_key", "api_base",
                "timeout", "num_retries", "max_retries", "model_info", "caching", "client", "litellm_logging_obj")
    if set(data) - set(allowed + (internal if physical else ())):
        raise ValidationError("Unsupported request settings/tools/billing path; no paid attempt is permitted.")
    expected = (envelope.provider_model, "openai/" + envelope.provider_model) if physical else (envelope.gateway_model,)
    if data.get("model") not in expected:
        raise ValidationError("Request model differs from the immutable task/provider binding.")
    if data.get("n", 1) != 1 or type(data.get("n", 1)) is not int or data.get("store", False) is not False:
        raise ValidationError("Only one unstored text completion is supported.")
    if data.get("service_tier", "default") != "default":
        raise ValidationError("Only the reviewed default billing tier is supported.")
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValidationError("A text chat request requires messages.")
    if local:
        local_chat(data, envelope)
    else:
        for message in messages:
            if not isinstance(message, dict) or set(message) != {"role", "content"} or message["role"] not in ("system", "developer", "user", "assistant") or not isinstance(message["content"], str):
                raise ValidationError("Non-text, tool, prediction, cache-write, and plugin billing paths are unsupported.")
    stream = data.get("stream", False)
    if type(stream) is not bool:
        raise ValidationError("Stream must be an explicit boolean.")
    if stream and data.get("stream_options") != {"include_usage": True} or not stream and data.get("stream_options") is not None:
        raise ValidationError("Supported streaming must request final usage; interruption still leaves cost unknown.")
    output = data.get("max_completion_tokens")
    envelope.maximum(output)
    return {"output_limit": output, "stream": stream}


def _shape(value, allowed, required):
    # Inference content is allowed transiently here, NOT metadata for persistence.
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValidationError("Unsupported local-function chat structure; no raw content was retained.")
    return value


def _text_content(value, nullable=False):
    if nullable and value is None or isinstance(value, str):
        return
    if not isinstance(value, list) or not value:
        raise ValidationError("Only text strings/parts are supported by local function chat.")
    for part in value:
        _shape(part, ("type", "text"), ("type", "text"))
        if part["type"] != "text" or not isinstance(part["text"], str):
            raise ValidationError("Non-text or explicit cache-write input has no reviewed billing envelope.")


def local_chat(data, envelope):
    contracts = {tool.name: tool for tool in envelope.local_tools}
    definitions = data.get("tools", [])
    if not isinstance(definitions, list):
        raise ValidationError("Tools must be explicit local function definitions.")
    offered = set()
    for tool in definitions:
        _shape(tool, ("type", "function"), ("type", "function"))
        definition = _shape(tool["function"], ("name", "description", "parameters", "strict"), ("name", "parameters"))
        name = definition["name"]
        if tool["type"] != "function" or not isinstance(name, str) or name not in contracts or name in offered:
            raise ValidationError("Hosted/unapproved/duplicate functions are outside this task's local tool binding.")
        if (not isinstance(definition["parameters"], dict) or definition["parameters"].get("type") != "object"
            or "description" in definition and not isinstance(definition["description"], str)
            or "strict" in definition and type(definition["strict"]) is not bool):
            raise ValidationError("Local function definition has an unsupported schema/setting shape.")
        if function_fingerprint(definition) != contracts[name].function_sha256:
            raise ValidationError("Function definition changed from its independently reviewed binding.")
        offered.add(name)
    choice = data.get("tool_choice", "auto")
    if isinstance(choice, dict):
        _shape(choice, ("type", "function"), ("type", "function"))
        _shape(choice["function"], ("name",), ("name",))
        if choice["type"] != "function" or not isinstance(choice["function"]["name"], str) or choice["function"]["name"] not in offered:
            raise ValidationError("Tool choice must name an offered approved local function.")
    elif choice not in ("auto", "none", "required") or choice == "required" and not offered:
        raise ValidationError("Unknown/unsatisfied tool-choice path.")
    if type(data.get("parallel_tool_calls", False)) is not bool:
        raise ValidationError("Parallel local-function choice must be an explicit boolean.")
    for name, maximum in (("temperature", 2), ("top_p", 1)):
        if name in data and number(data[name], name) > maximum:
            raise ValidationError("Generation option is outside its supported bound.")
    if "stop" in data and not (isinstance(data["stop"], str) or isinstance(data["stop"], list) and len(data["stop"]) <= 4 and all(isinstance(value, str) for value in data["stop"])):
        raise ValidationError("Unsupported stop setting.")
    pending, seen = {}, set()
    for message in data["messages"]:
        if not isinstance(message, dict):
            raise ValidationError("Unsupported local-function message.")
        role = message.get("role")
        if role == "assistant":
            _shape(message, ("role", "content", "tool_calls", "refusal"), ("role",))
            if pending:
                raise ValidationError("Previous tool call has no complete linked result; continuation refused.")
            _text_content(message.get("content"), nullable=True)
            if message.get("refusal") is not None and not isinstance(message["refusal"], str):
                raise ValidationError("Unsupported refusal field.")
            calls = message.get("tool_calls", [])
            if calls is None:
                calls = []
            if not isinstance(calls, list):
                raise ValidationError("Assistant tool calls must be an array.")
            if message.get("content") is None and not calls and message.get("refusal") is None:
                raise ValidationError("Assistant message has no content, refusal or local function call.")
            for call in calls:
                _shape(call, ("id", "type", "function"), ("id", "type", "function"))
                function = _shape(call["function"], ("name", "arguments"), ("name", "arguments"))
                if (not isinstance(call["id"], str) or not call["id"] or call["id"] in seen or call["type"] != "function"
                    or not isinstance(function["name"], str) or function["name"] not in contracts or not isinstance(function["arguments"], str)):
                    raise ValidationError("Unapproved/duplicate tool call cannot be linked to this task.")
                seen.add(call["id"]); pending[call["id"]] = function["name"]
        elif role == "tool":
            _shape(message, ("role", "content", "tool_call_id"), ("role", "content", "tool_call_id"))
            identifier = message["tool_call_id"]
            if not isinstance(identifier, str) or identifier not in pending:
                raise ValidationError("Orphan/duplicate tool result cannot authorize a paid continuation.")
            _text_content(message["content"])
            del pending[identifier]
        elif role in ("user", "system", "developer"):
            _shape(message, ("role", "content"), ("role", "content"))
            if pending:
                raise ValidationError("Tool results must be complete before another request message.")
            _text_content(message["content"])
        else:
            raise ValidationError("Unsupported message role/billing path.")
    if pending:
        raise ValidationError("Incomplete tool results cannot enter another paid model attempt.")


def chat_usage(response):
    """Project documented chat usage; never read or copy choices/output text."""
    if not isinstance(response, dict):
        # LiteLLM ModelResponse supports field access without serializing content.
        getter = lambda key, default=None: getattr(response, key, default)
    else:
        getter = response.get
    usage = getter("usage")
    if usage is None:
        return None
    def get(value, key, default=None):
        return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)
    inputs, outputs = get(usage, "prompt_tokens"), get(usage, "completion_tokens")
    if inputs is None or outputs is None:
        return None
    prompt, completion = get(usage, "prompt_tokens_details"), get(usage, "completion_tokens_details")
    cached, reasoning = get(prompt, "cached_tokens"), get(completion, "reasoning_tokens")
    if cached is None or reasoning is None:
        # Missing optional counters are unknown, not measured zeros. The narrow
        # settlement path requires complete supported usage or independent billing.
        return None
    # Unknown extra billing is not a free charge. New modalities require a new envelope.
    for details, keys in ((prompt, ("audio_tokens", "image_tokens", "cache_write_tokens")),
                          (completion, ("audio_tokens", "accepted_prediction_tokens", "rejected_prediction_tokens"))):
        if any(get(details, key, 0) not in (None, 0) for key in keys):
            return None
    result = {"input_tokens": inputs, "output_tokens": outputs,
              "cached_input_tokens": cached, "reasoning_tokens": reasoning}
    for key in USAGE_FIELDS:
        integer(result[key], key)
    total = get(usage, "total_tokens")
    if total is not None and integer(total, "total_tokens") != inputs + outputs:
        raise ValidationError("Provider usage total contradicts input/output totals.")
    return result
