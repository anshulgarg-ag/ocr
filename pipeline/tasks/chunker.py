"""
Heading-aware Markdown chunker.

Strategy:
1. Parse Markdown into a section tree using H1/H2/H3 headings.
2. Split sections that exceed CHUNK_MAX_TOKENS at paragraph boundaries.
3. Apply a sliding overlap of CHUNK_OVERLAP_TOKENS between consecutive chunks.
4. Never split mid-sentence (spacy sentence boundaries as minimum unit).
5. Discard chunks smaller than MIN_CHUNK_TOKENS.
6. Assign deterministic UUID5 IDs per chunk.

Each chunk output:
{
  "chunk_id": str,     # uuid5(NAMESPACE_URL, f"{doc_id}:{chunk_index}")
  "doc_id": str,
  "chunk_index": int,
  "heading_path": str, # e.g. "Introduction > Background"
  "text": str,
  "token_count": int,
  "page_hint": str     # best-effort page reference from Markdown markers
}
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

import spacy

from config.settings import settings

MIN_CHUNK_TOKENS = 50
_APPROX_CHARS_PER_TOKEN = 4  # rough tokenisation estimate (no tokeniser dep)

_SENTENCIZER = None


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // _APPROX_CHARS_PER_TOKEN)


def _get_sentencizer():
    """Lazily build a lightweight spaCy pipeline (blank + rule-based sentencizer).

    Uses a blank language pipeline rather than a downloaded model — the
    sentencizer component only needs punctuation heuristics, so no model
    weights need to be shipped/downloaded for this to work.
    """
    global _SENTENCIZER
    if _SENTENCIZER is None:
        nlp = spacy.blank("en")
        nlp.add_pipe("sentencizer")
        _SENTENCIZER = nlp
    return _SENTENCIZER


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using spaCy sentence boundaries.

    Falls back to a lightweight regex splitter if spaCy is unavailable for
    any reason, so sentence-level packing keeps working regardless.
    """
    try:
        nlp = _get_sentencizer()
        sentences = [s.text.strip() for s in nlp(text).sents if s.text.strip()]
        if sentences:
            return sentences
    except Exception:
        pass
    # Regex fallback: split on sentence-ending punctuation followed by
    # whitespace, taking care not to split on common abbreviations.
    pattern = r"(?<!\b[A-Z][a-z])(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bDr)(?<!\bSt)(?<=[.!?])\s+"
    return [s.strip() for s in re.split(pattern, text) if s.strip()]


def _chunk_uuid(doc_id: str, idx: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{idx}"))


@dataclass
class _Section:
    heading: str
    level: int
    heading_path: str
    content_lines: list[str] = field(default_factory=list)


def _parse_sections(md: str) -> list[_Section]:
    """Split Markdown into sections delimited by headings."""
    sections: list[_Section] = []
    current = _Section(heading="__preamble__", level=0, heading_path="")
    heading_stack: list[str] = []

    for line in md.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            # Save current section
            if current.content_lines:
                sections.append(current)
            level = len(m.group(1))
            heading = m.group(2).strip()
            # Maintain heading stack
            while heading_stack and len(heading_stack) >= level:
                heading_stack.pop()
            heading_stack.append(heading)
            current = _Section(
                heading=heading,
                level=level,
                heading_path=" > ".join(heading_stack),
            )
        else:
            current.content_lines.append(line)

    if current.content_lines:
        sections.append(current)
    return sections


def _pack_units(units: list[str], max_tokens: int, overlap_tokens: int, sep: str) -> list[str]:
    """Greedily pack text units (paragraphs or sentences) into chunks ≤ max_tokens,
    carrying a trailing overlap of ~overlap_tokens between consecutive chunks."""
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for unit in units:
        unit_tokens = _approx_tokens(unit)
        if current_tokens + unit_tokens > max_tokens and current_parts:
            chunks.append(sep.join(current_parts))
            # Carry over trailing overlap
            overlap_text = " ".join(current_parts)[-overlap_tokens * _APPROX_CHARS_PER_TOKEN :]
            current_parts = [overlap_text] if overlap_text.strip() else []
            current_tokens = _approx_tokens(overlap_text)
        current_parts.append(unit)
        current_tokens += unit_tokens

    if current_parts:
        chunks.append(sep.join(current_parts))
    return chunks


def _merge_small_chunks(chunks: list[str], min_tokens: int, sep: str = "\n\n") -> list[str]:
    """Merge a chunk that falls below min_tokens into the following chunk.

    Packing greedily to a max_tokens ceiling can leave small leftover
    fragments (e.g. the tail of a sentence-split paragraph). Rather than
    silently discarding that real content downstream, fold it forward so
    only genuinely insufficient total content (less than min_tokens even
    after merging everything available) ends up filtered out.
    """
    if not chunks:
        return chunks
    merged: list[str] = []
    buffer = chunks[0]
    for nxt in chunks[1:]:
        if _approx_tokens(buffer) < min_tokens:
            buffer = sep.join([buffer, nxt])
        else:
            merged.append(buffer)
            buffer = nxt
    merged.append(buffer)
    return merged


def _split_by_paragraphs(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Split text into chunks ≤ max_tokens with overlap.

    Paragraphs are the primary unit. A paragraph that itself exceeds
    max_tokens (e.g. one long block of prose with no blank lines) is
    subdivided at sentence boundaries — never mid-sentence — and packed
    the same way paragraphs are. The sentence-packed pieces are emitted
    as finished chunks directly (rather than re-fed through paragraph
    packing) so overlap is only ever applied once per boundary.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = _approx_tokens(para)

        if para_tokens > max_tokens:
            # Flush whatever normal paragraphs have accumulated so far.
            if current_parts:
                chunks.append("\n\n".join(current_parts))
                current_parts = []
                current_tokens = 0
            sentences = _split_sentences(para)
            if len(sentences) > 1:
                chunks.extend(_pack_units(sentences, max_tokens, overlap_tokens, sep=" "))
            else:
                chunks.append(para)
            continue

        if current_tokens + para_tokens > max_tokens and current_parts:
            chunks.append("\n\n".join(current_parts))
            # Carry over trailing overlap
            overlap_text = " ".join(current_parts)[-overlap_tokens * _APPROX_CHARS_PER_TOKEN :]
            current_parts = [overlap_text] if overlap_text.strip() else []
            current_tokens = _approx_tokens(overlap_text)
        current_parts.append(para)
        current_tokens += para_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))
    return _merge_small_chunks(chunks, MIN_CHUNK_TOKENS)


def chunk_markdown(markdown: str, doc_id: str) -> list[dict]:
    """
    Chunk a Markdown document into semantically coherent pieces.
    Returns a list of chunk dicts ready for embedding.
    """
    sections = _parse_sections(markdown)
    max_tok = settings.chunk_max_tokens
    overlap_tok = settings.chunk_overlap_tokens
    chunks: list[dict] = []
    idx = 0

    for section in sections:
        section_text = "\n".join(section.content_lines).strip()
        if not section_text:
            continue

        if _approx_tokens(section_text) <= max_tok:
            sub_chunks = [section_text]
        else:
            sub_chunks = _split_by_paragraphs(section_text, max_tok, overlap_tok)

        for sub in sub_chunks:
            token_count = _approx_tokens(sub)
            if token_count < MIN_CHUNK_TOKENS:
                continue
            chunks.append(
                {
                    "chunk_id": _chunk_uuid(doc_id, idx),
                    "doc_id": doc_id,
                    "chunk_index": idx,
                    "heading_path": section.heading_path,
                    "text": sub,
                    "token_count": token_count,
                }
            )
            idx += 1

    return chunks


def chunks_to_jsonl(chunks: list[dict]) -> str:
    return "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks)


def jsonl_to_chunks(jsonl: str) -> list[dict]:
    return [json.loads(line) for line in jsonl.splitlines() if line.strip()]
