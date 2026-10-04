"""Explicit dotted INSTANCE entrypoint for an existing company LiteLLM Proxy.

Only import after operator callback-loading approval. Neither company launcher
nor the offline engine imports this module automatically.
"""

from engine.gateway_startup import callback_from_environment


callback = callback_from_environment()
