"""Loads source-controlled knowledge documents from the ONE explicitly
configured/allowlisted root (Phase 6 §5/§6) -- `IndexingBounds.
knowledge_root`, set only by an operator/deployment environment
variable, never by a request parameter. `load_knowledge_documents`
resolves every candidate file and verifies it is still inside that
root (defends against a symlink pointing outside it); nothing in this
module ever accepts or constructs a path from untrusted input.
"""

import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeDocument:
    source_key: str
    title: str
    text: str


def _title_from_markdown(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def load_knowledge_documents(knowledge_root: str) -> list[KnowledgeDocument]:
    """Deterministic, stable ordering (sorted by relative path) --
    never dependent on filesystem iteration order. Only `*.md` files
    directly under the allowlisted root (recursively) are considered;
    no other extension is read, and no path outside the resolved root
    is ever returned.
    """
    root = pathlib.Path(knowledge_root).resolve()
    if not root.is_dir():
        return []

    documents: list[KnowledgeDocument] = []
    for path in sorted(root.rglob("*.md")):
        resolved = path.resolve()
        # Defends against a symlink inside the allowlisted root that
        # points somewhere else on the filesystem -- the resolved,
        # real path must still be a descendant of `root`.
        if root not in resolved.parents and resolved != root:
            continue
        try:
            resolved.relative_to(root)
        except ValueError:
            continue

        text = resolved.read_text(encoding="utf-8")
        source_key = str(resolved.relative_to(root)).replace("\\", "/")
        documents.append(
            KnowledgeDocument(source_key=source_key, title=_title_from_markdown(text, source_key), text=text)
        )

    return documents
