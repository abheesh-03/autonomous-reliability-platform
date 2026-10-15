"""Tests for chunking.py -- Phase 6 §6's deterministic chunking
requirements: stable ordering, bounded chunk size, bounded overlap,
content hashing, Markdown/heading awareness."""

from retrieval_service.chunking import chunk_text, content_hash


def test_chunking_is_deterministic_across_calls():
    text = "# Heading\n\nSome content here.\n\n## Subheading\n\nMore content."
    assert chunk_text(text, 50, 10) == chunk_text(text, 50, 10)


def test_chunks_respect_the_max_chars_bound():
    text = "word " * 2000
    chunks = chunk_text(text, max_chars=300, overlap_chars=20)
    assert chunks
    assert all(len(c) <= 300 for c in chunks)


def test_heading_starts_a_new_chunk_when_possible():
    text = "intro text\n\n# Real Heading\nbody under heading"
    chunks = chunk_text(text, max_chars=1000, overlap_chars=0)
    # Small enough to fit in one chunk when there's plenty of room --
    # heading-awareness only matters once bounds force a split, so use
    # a tighter bound to force two chunks and confirm the heading
    # starts the second one, not mid-sentence.
    chunks = chunk_text(text, max_chars=15, overlap_chars=0)
    assert any(c.startswith("# Real Heading") for c in chunks)


def test_empty_text_produces_no_chunks():
    assert chunk_text("", 100, 10) == []
    assert chunk_text("   \n\n  ", 100, 10) == []


def test_overlap_is_bounded_and_never_exceeds_max_chars():
    text = "x" * 5000
    chunks = chunk_text(text, max_chars=200, overlap_chars=5000)  # deliberately huge overlap request
    assert all(len(c) <= 200 for c in chunks)


def test_no_duplicate_identical_chunks_for_simple_repeated_input():
    text = "\n\n".join(f"Paragraph number {i} with some unique content." for i in range(20))
    chunks = chunk_text(text, max_chars=200, overlap_chars=20)
    assert len(chunks) == len(set(chunks))  # every chunk's content is distinct here


def test_content_hash_is_deterministic_and_sensitive_to_change():
    a = content_hash("hello world")
    b = content_hash("hello world")
    c = content_hash("hello world!")
    assert a == b
    assert a != c
    assert len(a) == 64  # sha256 hex digest
