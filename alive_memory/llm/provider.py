"""LLM provider protocol."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol that any LLM backend must implement."""

    async def complete(self, prompt: str, max_tokens: int = 1000) -> str:
        """Generate a completion from the given prompt."""
        ...
