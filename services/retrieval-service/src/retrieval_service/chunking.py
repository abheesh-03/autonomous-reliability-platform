"""Deterministic knowledge chunking (Phase 6 §6).

`chunk_text` always produces the SAME ordered list of chunk strings
for the SAME input text, bounds, and overlap -- no randomness, no
wall-clock dependency, no filesystem traversal of its own (callers
decide what text to pass in; see knowledge.py for the one allowlisted
root this is ever called against). This is what makes re-indexing
idempotent: `indexer.py` pairs each chunk's position in this list with
its source_key as a stable (source_key, chunk_index) identity, and
hashes its exact content -- an unchanged chunk re-hashes to the same
content_hash and upserts onto the same row (see V5's uniqueness
constraint); a changed chunk updates in place; a chunk that no longer
exists past the new chunk count is deleted (stale-chunk cleanup).

Markdown/heading-aware (Phase 6 §6: "reasonable Markdown/heading
awareness if practical"): a line starting with "#" always begins a
new accumulation unit, so a heading and the content immediately under
it are kept together rather than arbitrarily split mid-heading. This
is a practical heuristic, not a real Markdown parser -- it does not
understand code fences, tables, or nested structure.
"""

import hashlib

_HEADING_PREFIX = "#"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _blocks(text: str) -> list[str]:
    """Splits into paragraph-like blocks on blank lines, but always
    starts a new block at a Markdown heading line, even if the
    preceding line wasn't blank -- stable, deterministic, and
    independent of wall-clock/filesystem state."""
    lines = text.splitlines()
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            joined = "\n".join(current).strip()
            if joined:
                blocks.append(joined)
            current.clear()

    for line in lines:
        is_heading = line.lstrip().startswith(_HEADING_PREFIX)
        if is_heading and current:
            flush()
        if not line.strip() and current:
            flush()
            continue
        if not line.strip() and not current:
            continue
        current.append(line)
    flush()
    return blocks


def _hard_split(block: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Fallback for a single block that alone exceeds max_chars (e.g.
    one very long paragraph with no internal blank lines) -- bounded,
    deterministic, fixed-stride slicing with bounded overlap."""
    if max_chars <= 0:
        return [block]
    stride = max(1, max_chars - overlap_chars)
    pieces = []
    start = 0
    while start < len(block):
        pieces.append(block[start : start + max_chars])
        start += stride
    return pieces


def chunk_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Returns a stable, ordered list of non-empty chunk strings, each
    at most `max_chars` long (aside from the hard-split fallback's own
    slicing, which is itself bounded to max_chars per piece), with up
    to `overlap_chars` of trailing context from the previous chunk
    carried into the next one so a concept split across a chunk
    boundary isn't entirely lost to either side.
    """
    overlap_chars = min(overlap_chars, max(0, max_chars - 1))
    blocks = _blocks(text)
    if not blocks:
        return []

    chunks: list[str] = []
    current = ""

    def finalize(next_seed: str = "") -> str:
        if current.strip():
            chunks.append(current.strip())
        if overlap_chars > 0 and current:
            tail = current[-overlap_chars:]
            return (tail + "\n" + next_seed).strip("\n") if next_seed else tail
        return next_seed

    for block in blocks:
        if len(block) > max_chars:
            # This single block alone is too large -- flush whatever
            # has accumulated so far, then hard-split the oversized
            # block on its own.
            current = finalize()
            for piece in _hard_split(block, max_chars, overlap_chars):
                if piece.strip():
                    chunks.append(piece.strip())
            current = ""
            continue

        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) > max_chars and current:
            current = finalize(block)
        else:
            current = candidate

    if current.strip():
        chunks.append(current.strip())

    return chunks
