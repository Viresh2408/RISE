"""LLM Gateway — public surface.

Typical import::

    from llm_gateway import call_structured, LLMGateway, GatewayConfig, ProviderConfig
    from llm_gateway.exceptions import (
        LLMGatewayError, ProviderError, StructuredOutputError, AllProvidersFailedError
    )
"""

from llm_gateway.config import GatewayConfig, ProviderConfig
from llm_gateway.exceptions import (
    AllProvidersFailedError,
    LLMGatewayError,
    ProviderError,
    StructuredOutputError,
)
from llm_gateway.gateway import LLMGateway, call_structured
from llm_gateway.usage import LLMUsageLog

__all__ = [
    "call_structured",
    "GatewayConfig",
    "ProviderConfig",
    "LLMGateway",
    "LLMUsageLog",
    "LLMGatewayError",
    "ProviderError",
    "StructuredOutputError",
    "AllProvidersFailedError",
]
