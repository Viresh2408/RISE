"""LLM Gateway exception hierarchy.

Three leaf classes cover the three distinct failure modes the gateway surfaces:
- ProviderError     — network/timeout/HTTP error from a provider adapter
- StructuredOutputError — provider responded but repair failed to produce valid JSON
- AllProvidersFailedError — every configured provider raised ProviderError
"""

from __future__ import annotations


class LLMGatewayError(Exception):
    """Base for all LLM Gateway errors."""


class ProviderError(LLMGatewayError):
    """Raised by a provider adapter when the HTTP call fails (timeout, 5xx, network).

    Catching this at the gateway level triggers failover to the next provider.
    """

    def __init__(
        self,
        provider_name: str,
        original: BaseException,
        *,
        timeout: bool = False,
    ) -> None:
        self.provider_name = provider_name
        self.original = original
        self.timeout = timeout
        super().__init__(
            f"[{provider_name}] {'Timeout' if timeout else 'Provider'} error: {original}"
        )


class StructuredOutputError(LLMGatewayError):
    """Raised when a provider responded but the output (including after repair) is not
    valid against the requested Pydantic schema.

    Never raised silently — always carries the raw content that failed validation.
    """

    def __init__(self, provider_name: str, bad_content: str) -> None:
        self.provider_name = provider_name
        self.bad_content = bad_content
        super().__init__(
            f"[{provider_name}] Structured output validation failed after repair attempt. "
            f"Bad content (truncated): {bad_content[:200]!r}"
        )


class AllProvidersFailedError(LLMGatewayError):
    """Raised when every provider in the configured chain raised ProviderError."""

    def __init__(self, attempted: list[str]) -> None:
        self.attempted = attempted
        super().__init__(
            f"All configured LLM providers failed. Attempted: {attempted}"
        )
