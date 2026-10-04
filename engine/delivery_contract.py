"""Narrow text-chat billing contract. No provider transport or production prices."""

from dataclasses import dataclass
from decimal import Decimal, localcontext

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
        data = {key: getattr(self, key) for key in self.__dataclass_fields__}
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


def chat_request(data, envelope, physical=False):
    """Inspect inference data only inside the authorized gateway; return metadata only."""
    allowed = ("model", "messages", "max_completion_tokens", "stream", "stream_options", "n", "store", "metadata", "service_tier")
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
