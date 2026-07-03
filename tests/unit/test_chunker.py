import pytest
from pipeline.tasks.chunker import chunk_markdown, chunks_to_jsonl, jsonl_to_chunks


def test_basic_split(sample_markdown):
    chunks = chunk_markdown(sample_markdown, doc_id="doc-001")
    assert len(chunks) > 0
    for c in chunks:
        assert c["doc_id"] == "doc-001"
        assert c["text"].strip()
        assert c["token_count"] >= 1


def test_heading_path_preserved(sample_markdown):
    chunks = chunk_markdown(sample_markdown, doc_id="doc-001")
    paths = [c["heading_path"] for c in chunks]
    assert any("Section 1" in p for p in paths)
    assert any("Section 2" in p for p in paths)


def test_chunk_ids_are_deterministic(sample_markdown):
    chunks_a = chunk_markdown(sample_markdown, doc_id="doc-001")
    chunks_b = chunk_markdown(sample_markdown, doc_id="doc-001")
    ids_a = [c["chunk_id"] for c in chunks_a]
    ids_b = [c["chunk_id"] for c in chunks_b]
    assert ids_a == ids_b


def test_min_token_filter(sample_markdown):
    chunks = chunk_markdown(sample_markdown, doc_id="doc-001")
    assert all(c["token_count"] >= 50 for c in chunks)


def test_different_doc_ids_produce_different_chunk_ids(sample_markdown):
    chunks_a = chunk_markdown(sample_markdown, doc_id="doc-001")
    chunks_b = chunk_markdown(sample_markdown, doc_id="doc-002")
    ids_a = set(c["chunk_id"] for c in chunks_a)
    ids_b = set(c["chunk_id"] for c in chunks_b)
    assert ids_a.isdisjoint(ids_b)


def test_chunks_to_jsonl_roundtrip(sample_markdown):
    """Verify chunks_to_jsonl and jsonl_to_chunks preserve data."""
    chunks = chunk_markdown(sample_markdown, doc_id="doc-001")

    jsonl = chunks_to_jsonl(chunks)
    assert jsonl
    assert "\n" in jsonl

    recovered = jsonl_to_chunks(jsonl)
    assert len(recovered) == len(chunks)

    for orig, recov in zip(chunks, recovered):
        assert orig["chunk_id"] == recov["chunk_id"]
        assert orig["doc_id"] == recov["doc_id"]
        assert orig["text"] == recov["text"]


def test_jsonl_to_chunks_skips_blank_lines():
    """Verify jsonl_to_chunks ignores blank lines."""
    import json

    chunks = [
        {"chunk_id": "c1", "text": "Text 1"},
        {"chunk_id": "c2", "text": "Text 2"},
    ]

    jsonl_with_blanks = (
        json.dumps(chunks[0]) + "\n"
        + "\n"
        + json.dumps(chunks[1]) + "\n"
        + "   \n"
    )

    recovered = jsonl_to_chunks(jsonl_with_blanks)
    assert len(recovered) == 2


def test_empty_markdown_returns_empty_chunks():
    """Verify empty markdown produces no chunks."""
    chunks = chunk_markdown("", doc_id="doc-001")
    assert chunks == []


def test_markdown_with_only_headings_no_content():
    """Verify markdown with only headings and no content."""
    markdown = "# Title\n## Section 1\n### Subsection\n## Section 2"
    chunks = chunk_markdown(markdown, doc_id="doc-001")
    assert chunks == []


def test_oversized_section_with_tiny_chunk_max(monkeypatch):
    """Verify paragraph splitting works for oversized sections."""
    from config.settings import settings

    monkeypatch.setattr(settings, "chunk_max_tokens", 20)
    monkeypatch.setattr(settings, "chunk_overlap_tokens", 5)

    markdown = (
        "# Main Section\n\n"
        "This is a very long paragraph with lots of content. "
        "It contains many sentences to ensure it exceeds the small chunk_max_tokens limit. "
        "We need to test the paragraph splitting logic in the chunker. "
        "This text should be split across multiple chunks. "
        "Each chunk should contain overlapping content from the previous one. "
        "The overlap is used to maintain context across chunk boundaries. "
        "This is important for semantic understanding of the document. "
    )

    chunks = chunk_markdown(markdown, doc_id="doc-001")
    assert len(chunks) > 1


def test_chunk_below_min_tokens_discarded(monkeypatch):
    """Verify chunks below MIN_CHUNK_TOKENS are discarded."""
    from config.settings import settings

    monkeypatch.setattr(settings, "chunk_max_tokens", 10)

    markdown = (
        "# Main Section\n\n"
        "Short text. Very brief. "
        "This whole section won't have enough tokens to meet the minimum. "
        "Even with multiple sentences, it's still quite small overall. "
    )

    chunks = chunk_markdown(markdown, doc_id="doc-001")
    assert all(c["token_count"] >= 50 for c in chunks)
