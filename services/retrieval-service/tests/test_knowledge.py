"""Tests for knowledge.py -- Phase 6 §5/§6: only the explicitly
allowlisted root is ever read, no arbitrary filesystem traversal, and
deterministic, stable ordering."""

import os

from retrieval_service.knowledge import load_knowledge_documents


def test_missing_root_returns_empty_list(tmp_path):
    assert load_knowledge_documents(str(tmp_path / "does-not-exist")) == []


def test_loads_markdown_files_with_deterministic_sorted_ordering(tmp_path):
    (tmp_path / "b.md").write_text("# B Title\nbody b")
    (tmp_path / "a.md").write_text("# A Title\nbody a")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.md").write_text("# C Title\nbody c")

    docs = load_knowledge_documents(str(tmp_path))
    assert [d.source_key for d in docs] == ["a.md", "b.md", "sub/c.md"]


def test_non_markdown_files_are_ignored(tmp_path):
    (tmp_path / "readme.txt").write_text("not markdown")
    (tmp_path / "real.md").write_text("# Real\nbody")
    docs = load_knowledge_documents(str(tmp_path))
    assert [d.source_key for d in docs] == ["real.md"]


def test_title_extracted_from_first_heading(tmp_path):
    (tmp_path / "x.md").write_text("intro line\n# The Real Title\nbody")
    docs = load_knowledge_documents(str(tmp_path))
    assert docs[0].title == "The Real Title"


def test_title_falls_back_to_source_key_when_no_heading(tmp_path):
    (tmp_path / "x.md").write_text("just plain text, no heading at all")
    docs = load_knowledge_documents(str(tmp_path))
    assert docs[0].title == "x.md"


def test_symlink_escaping_the_allowlisted_root_is_refused(tmp_path):
    """Phase 6 §6: 'no arbitrary filesystem traversal' -- a symlink
    inside the allowlisted root that points OUTSIDE it must never be
    followed into indexing."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("# Secret\nshould never be indexed")

    root = tmp_path / "knowledge_root"
    root.mkdir()
    try:
        os.symlink(outside / "secret.md", root / "escape.md")
    except (OSError, NotImplementedError):
        import pytest

        pytest.skip("symlinks not supported in this test environment")

    docs = load_knowledge_documents(str(root))
    assert docs == []


def test_source_key_uses_forward_slashes(tmp_path):
    sub = tmp_path / "nested" / "dir"
    sub.mkdir(parents=True)
    (sub / "f.md").write_text("# F\nbody")
    docs = load_knowledge_documents(str(tmp_path))
    assert docs[0].source_key == "nested/dir/f.md"
    assert "\\" not in docs[0].source_key
