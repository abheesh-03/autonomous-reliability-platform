"""The LLM provider seam (Phase 5 §6).

`LLMProvider` is the Protocol every provider implements; production
code is wired to `OpenAIProvider` (the one real, configurable
provider), and tests inject `StubProvider` instead — never a real,
paid API call in CI. Neither provider implementation has, or is given,
any tool/function-calling capability: no shell, no HTTP tool, no
database access, no Docker access. The only thing either returns is a
single block of text this service's own code parses and validates
(see llm/validation.py) — the model itself executes nothing.
"""

import logging
from typing import Protocol

from openai import AsyncOpenAI, OpenAIError

logger = logging.getLogger("investigator_service.llm")


class ProviderError(Exception):
    """Raised on any provider call failure — timeout, connection
    error, non-2xx, or a response with no content. Deliberately never
    constructed from the SDK's own raw exception message (Phase 5
    correction round #7: that message is not GUARANTEED secret-free —
    relying on an upstream SDK's error-formatting behavior never
    including a credential is an assumption this service should not
    make). Only the exception's *type name* is ever included; the
    full exception is still logged server-side (exc_info=True, see
    api/investigations.py), a different and already-trusted
    destination, never the HTTP response body."""


class LLMProvider(Protocol):
    name: str
    model: str | None

    async def investigate(self, system_prompt: str, user_prompt: str) -> str:
        """Returns the raw text the model produced (expected to be a
        single JSON object per llm/prompt.py's instructions). Raises
        ProviderError on any failure. Never raises for "the model
        disagreed with the evidence" — only for actual call failures;
        schema/content validation happens entirely in
        llm/validation.py, after this returns."""
        ...


class OpenAIProvider:
    """The one real, configurable provider: OpenAI's Chat Completions
    API (or an OpenAI-compatible endpoint via `base_url`). Constructed
    only when LLMSettings.configured is True (see investigator.py) —
    never constructed with an empty API key."""

    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str | None, timeout_seconds: float) -> None:
        self.model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,  # this service owns its own retry/backoff policy, not the SDK's default
        )

    async def investigate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
        except OpenAIError as exc:
            # Only the exception TYPE name is included -- see
            # ProviderError's own docstring for why the raw SDK
            # message is deliberately never trusted or forwarded.
            raise ProviderError(f"{type(exc).__name__} from the LLM provider") from exc

        choice = response.choices[0] if response.choices else None
        content = choice.message.content if choice and choice.message else None
        if not content:
            raise ProviderError("provider returned an empty response")
        return content


class StubProvider:
    """Deterministic, offline provider for tests and CI — never makes
    a network call. Returns a fixed or caller-supplied JSON string, so
    tests can exercise the full orchestration/validation path
    (including deliberately malformed or evidence-fabricating output)
    without touching a real, paid API."""

    name = "stub"
    model = "stub-deterministic-v1"

    def __init__(self, response_text: str | None = None) -> None:
        self._response_text = response_text

    async def investigate(self, system_prompt: str, user_prompt: str) -> str:
        if self._response_text is not None:
            return self._response_text
        # Phase 5 correction round #1: cites a real evidence id (E1 is
        # always the incident-identity item — see
        # evidence_collector.py's construction order and
        # llm/prompt.py's selection policy, which always keeps it) so
        # that tests and scripts/verify-investigator.sh exercise the
        # ACTUAL citation-validation path end to end, rather than
        # trivially passing with every analysis section empty.
        return (
            '{"summary": "Stub investigation: deterministic test response, not a real AI analysis.", '
            '"observations": [{"statement": "A real incident record was retrieved and is described in E1.", '
            '"evidence_ids": ["E1"]}], '
            '"hypotheses": [], "missing_evidence": [], '
            '"suggested_checks": []}'
        )
