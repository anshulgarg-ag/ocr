import pytest
from unittest.mock import patch, MagicMock
from pipeline.tasks.discovery import find_new_files, SUPPORTED_EXTENSIONS


@pytest.mark.asyncio
async def test_find_new_files_returns_only_unknown():
    mock_files = ["raw/doc1.pdf", "raw/doc2.pdf", "raw/doc3.png"]
    known_hashes = {"hash_of_doc1"}

    def mock_list(*args, **kwargs):
        return mock_files

    def mock_etag(path):
        mapping = {
            "raw/doc1.pdf": "hash_of_doc1",
            "raw/doc2.pdf": "hash_of_doc2",
            "raw/doc3.png": "hash_of_doc3",
        }
        return mapping.get(path, "unknown_hash")

    with (
        patch("pipeline.tasks.discovery.storage_ops.list_files", side_effect=mock_list),
        patch("pipeline.tasks.discovery.storage_ops.etag", side_effect=mock_etag),
    ):
        result = await find_new_files(known_hashes)

    assert len(result) == 2
    hashes = {r["file_hash"] for r in result}
    assert "hash_of_doc1" not in hashes
    assert "hash_of_doc2" in hashes
    assert "hash_of_doc3" in hashes


@pytest.mark.asyncio
async def test_find_new_files_empty_when_all_known():
    with (
        patch("pipeline.tasks.discovery.storage_ops.list_files", return_value=["raw/a.pdf"]),
        patch("pipeline.tasks.discovery.storage_ops.etag", return_value="known_hash"),
    ):
        result = await find_new_files({"known_hash"})
    assert result == []
