import pytest
from pipeline.tasks.chunker import chunk_markdown, _approx_tokens

SAMPLE_MD = """
# Introduction

This is the introduction section. It contains some text about the project.
More text here to make it a bit longer and test chunking behavior.

## Background

The background section explains context. Companies like Acme Corp have used
similar approaches. The project started in 2023 and has grown significantly.

### Technical Details

Here are the technical details. This section goes into depth about the
implementation and architecture decisions made during development.

## Results

Results section contains findings. The accuracy improved by 15% over baseline.
Multiple experiments were conducted to validate the approach.
"""


def test_chunk_markdown_basic():
    chunks = chunk_markdown(SAMPLE_MD, "test-doc-123")
    assert len(chunks) >= 1
    for chunk in chunks:
        assert "chunk_id" in chunk
        assert "doc_id" in chunk
        assert chunk["doc_id"] == "test-doc-123"
        assert "text" in chunk
        assert "heading_path" in chunk
        assert "token_count" in chunk
        assert chunk["token_count"] > 0


def test_chunk_uuids_are_deterministic():
    chunks1 = chunk_markdown(SAMPLE_MD, "doc-abc")
    chunks2 = chunk_markdown(SAMPLE_MD, "doc-abc")
    ids1 = [c["chunk_id"] for c in chunks1]
    ids2 = [c["chunk_id"] for c in chunks2]
    assert ids1 == ids2


def test_chunk_uuids_differ_per_doc():
    chunks1 = chunk_markdown(SAMPLE_MD, "doc-001")
    chunks2 = chunk_markdown(SAMPLE_MD, "doc-002")
    ids1 = set(c["chunk_id"] for c in chunks1)
    ids2 = set(c["chunk_id"] for c in chunks2)
    assert ids1.isdisjoint(ids2)


def test_no_empty_chunks():
    chunks = chunk_markdown(SAMPLE_MD, "doc-xyz")
    for c in chunks:
        assert c["text"].strip() != ""


def test_approx_tokens():
    text = "hello world"  # 11 chars → ~2 tokens
    assert _approx_tokens(text) >= 1
