"""Test the LLM provider protocol."""

from alive_memory.llm.provider import LLMProvider


class MockProvider:
    """A mock LLM provider for testing."""

    async def complete(self, prompt: str, max_tokens: int = 1000) -> str:
        return f"Mock response to: {prompt[:50]}"


def test_mock_provider_satisfies_protocol():
    provider = MockProvider()
    assert isinstance(provider, LLMProvider)


def test_non_provider_fails_protocol():
    class NotAProvider:
        pass

    assert not isinstance(NotAProvider(), LLMProvider)
