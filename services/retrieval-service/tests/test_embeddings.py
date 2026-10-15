"""Tests for embeddings/provider.py -- Phase 6 §4's requirements for
the deterministic local provider (same text -> same vector, no
Python builtin hash(), fixed dimension, L2-normalized, no network)
and the OpenAI provider's missing-key/error-secrecy behavior."""

import math
import subprocess
import sys

import pytest

from retrieval_service.config import EMBEDDING_DIMENSION
from retrieval_service.embeddings.provider import (
    EmbeddingProviderError,
    LocalLexicalEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from retrieval_service.indexer import build_embedding_provider
from retrieval_service.config import EmbeddingSettings


async def test_local_provider_is_deterministic_within_a_process():
    provider = LocalLexicalEmbeddingProvider()
    [a] = await provider.embed(["checkout service returned 500 errors"])
    [b] = await provider.embed(["checkout service returned 500 errors"])
    assert a == b


def test_local_provider_is_stable_across_separate_processes():
    """Never uses Python's randomized built-in hash() -- confirmed by
    actually spawning a SEPARATE interpreter process (where
    PYTHONHASHSEED would differ by default) and checking the vector is
    byte-for-byte identical."""
    code = (
        "import asyncio, json, sys; sys.path.insert(0, 'src'); "
        "from retrieval_service.embeddings.provider import LocalLexicalEmbeddingProvider; "
        "p = LocalLexicalEmbeddingProvider(); "
        "print(json.dumps(asyncio.run(p.embed(['checkout service returned 500 errors']))[0]))"
    )
    out1 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=".")
    out2 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=".")
    assert out1.stdout == out2.stdout
    assert out1.stdout.strip() != ""


async def test_local_provider_vector_has_correct_dimension():
    provider = LocalLexicalEmbeddingProvider()
    [vec] = await provider.embed(["anything"])
    assert len(vec) == EMBEDDING_DIMENSION == 1536


async def test_local_provider_vector_is_l2_normalized():
    provider = LocalLexicalEmbeddingProvider()
    [vec] = await provider.embed(["checkout payment inventory notification"])
    norm = math.sqrt(sum(v * v for v in vec))
    assert abs(norm - 1.0) < 1e-9


async def test_local_provider_empty_text_still_returns_a_valid_normalized_vector():
    provider = LocalLexicalEmbeddingProvider()
    [vec] = await provider.embed([""])
    assert len(vec) == EMBEDDING_DIMENSION
    norm = math.sqrt(sum(v * v for v in vec))
    assert abs(norm - 1.0) < 1e-9


async def test_local_provider_different_text_usually_produces_different_vectors():
    provider = LocalLexicalEmbeddingProvider()
    [a] = await provider.embed(["checkout service"])
    [b] = await provider.embed(["completely unrelated other words here"])
    assert a != b


def test_local_provider_embedding_space_identity():
    provider = LocalLexicalEmbeddingProvider()
    assert provider.embedding_space == "local-lexical:hashing-v1:1536"


def test_openai_provider_missing_key_raises_not_configured_error_not_silent_fallback():
    from retrieval_service.embeddings.provider import EmbeddingProviderNotConfiguredError

    settings = EmbeddingSettings(provider="openai", api_key=None, model="text-embedding-3-small", base_url=None, timeout_seconds=5.0)
    with pytest.raises(EmbeddingProviderNotConfiguredError):
        build_embedding_provider(settings)


def test_default_provider_is_local_when_unspecified():
    settings = EmbeddingSettings(provider="local", api_key=None, model="unused", base_url=None, timeout_seconds=5.0)
    provider = build_embedding_provider(settings)
    assert isinstance(provider, LocalLexicalEmbeddingProvider)


async def test_openai_provider_error_never_exposes_raw_exception_message():
    """Same reasoning as investigator_service.llm.provider.ProviderError:
    an upstream SDK's own error-formatting behavior is not GUARANTEED
    to never include a credential, so only the exception's TYPE name
    is ever surfaced."""

    class _ExplodingClient:
        class embeddings:  # noqa: N801 -- mirrors the real openai.AsyncOpenAI client surface
            @staticmethod
            async def create(**kwargs):
                from openai import APIConnectionError

                raise APIConnectionError(request=None, message="sk-should-never-leak-this-secret")

    provider = OpenAIEmbeddingProvider(api_key="sk-test", model="text-embedding-3-small", base_url=None, timeout_seconds=1.0)
    provider._client = _ExplodingClient()  # replace the real SDK client with a controlled double

    with pytest.raises(EmbeddingProviderError) as exc_info:
        await provider.embed(["text"])
    assert "sk-should-never-leak-this-secret" not in str(exc_info.value)
    assert "APIConnectionError" in str(exc_info.value)
