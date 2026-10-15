"""The embedding provider seam (Phase 6 §4).

Two implementations:
  - `LocalLexicalEmbeddingProvider`: a DETERMINISTIC LEXICAL
    feature-hashing embedding. This is explicitly NOT a neural or
    semantic model -- it has no notion of word meaning, synonyms, or
    context; it only hashes tokens into fixed buckets. It exists so
    tests, CI, and the deterministic retrieval-quality smoke test
    (Phase 6 §18) never need network access or a paid API key, and so
    the exact same text always produces the exact same vector, on any
    machine, in any process, forever (no PYTHONHASHSEED-style
    randomization, since it never calls Python's builtin `hash()` --
    only `hashlib.sha256`, which is stable across processes/platforms
    by design).
  - `OpenAIEmbeddingProvider`: a real, configurable embedding model
    (e.g. `text-embedding-3-small`), via a SEPARATE credential
    (`RETRIEVAL_EMBEDDING_API_KEY`) from investigator-service's own
    `INVESTIGATOR_LLM_API_KEY` -- this service has no reason to ever
    see that one. Never prints or logs the API key; any provider
    failure is wrapped in `EmbeddingProviderError` with only the
    exception's type name, never its raw message (same reasoning as
    investigator_service.llm.provider.ProviderError: an upstream SDK's
    error-formatting behavior is not GUARANTEED to never include a
    credential).

Every embedding vector is L2-normalized before being returned, so a
plain dot product and pgvector's `<=>` (cosine distance) agree -- see
search.py.
"""

import hashlib
import logging
import math
import re
from typing import Protocol

from openai import AsyncOpenAI, OpenAIError

from retrieval_service.config import EMBEDDING_DIMENSION

logger = logging.getLogger("retrieval_service.embeddings")

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class EmbeddingProviderError(Exception):
    """Raised on any embedding call failure. Never constructed from a
    raw upstream SDK exception message -- only its type name."""


class EmbeddingProviderNotConfiguredError(Exception):
    """Raised at construction time when `provider="openai"` is
    selected but no API key is configured (Phase 6 §4: "fail
    explicitly", never a silent fallback to the local provider)."""


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimension: int

    @property
    def embedding_space(self) -> str:
        """`"<provider>:<model>:<dimension>"` -- the exact string
        stored in reliability.retrieval_chunks.embedding_space and
        used to scope every search query, so vectors from
        incompatible providers/models are never compared (Phase 6
        §4)."""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Returns one L2-normalized vector of `dimension` floats per
        input text, in the same order. Raises EmbeddingProviderError
        on failure."""
        ...


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        # Degenerate-but-defined fallback (Phase 6 §4): an empty or
        # entirely-unrecognized-token input would otherwise produce a
        # zero vector, which cosine distance cannot meaningfully
        # compare against anything (division by zero). A fixed unit
        # vector at index 0 is still deterministic and stable, and is
        # never mistaken for a real match (every real chunk's own text
        # is non-empty, enforced by V5's `content` CHECK constraint).
        vector = [0.0] * len(vector)
        vector[0] = 1.0
        return vector
    return [v / norm for v in vector]


class LocalLexicalEmbeddingProvider:
    """Deterministic lexical feature-hashing embedding -- see module
    docstring. NOT a neural/semantic model: two sentences with the
    same words in a different order, or synonyms for the same concept,
    are not specially related by this provider beyond shared tokens.
    """

    name = "local-lexical"
    model = "hashing-v1"
    dimension = EMBEDDING_DIMENSION

    @property
    def embedding_space(self) -> str:
        return f"{self.name}:{self.model}:{self.dimension}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], "big") % self.dimension
            sign = 1.0 if (digest[8] & 1) == 0 else -1.0
            vector[bucket] += sign
        return _l2_normalize(vector)


class OpenAIEmbeddingProvider:
    """Real, configurable embedding provider. Constructed only when
    EmbeddingSettings.provider == "openai" AND api_key is present --
    see main.py's _build_embedding_provider, which raises
    EmbeddingProviderNotConfiguredError otherwise rather than silently
    substituting the local provider.
    """

    name = "openai"
    dimension = EMBEDDING_DIMENSION

    def __init__(self, api_key: str, model: str, base_url: str | None, timeout_seconds: float) -> None:
        self.model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )

    @property
    def embedding_space(self) -> str:
        return f"{self.name}:{self.model}:{self.dimension}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self._client.embeddings.create(
                model=self.model,
                input=texts,
                # Forces exactly EMBEDDING_DIMENSION regardless of
                # which text-embedding-3-* model is configured (both
                # support OpenAI's "dimensions" truncation parameter)
                # -- Phase 6 §3/§4's "one fixed embedding dimension
                # consistently across providers and the schema".
                dimensions=self.dimension,
            )
        except OpenAIError as exc:
            # Only the exception TYPE name -- never the raw SDK
            # message (see module docstring / ProviderError's own
            # reasoning in investigator-service).
            raise EmbeddingProviderError(f"{type(exc).__name__} from the embedding provider") from exc

        by_index = {item.index: item.embedding for item in response.data}
        if len(by_index) != len(texts):
            raise EmbeddingProviderError("embedding provider returned a different number of vectors than requested")
        return [_l2_normalize(list(by_index[i])) for i in range(len(texts))]
