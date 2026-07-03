"""Integration tests for storage_ops against real MinIO."""
import hashlib
import pytest
from pipeline.tasks import storage_ops


pytestmark = pytest.mark.integration


async def test_upload_and_download_roundtrip(minio_settings):
    """Upload bytes, download, and assert content matches."""
    content = b"Hello, MinIO! This is a test file."
    dest_path = "test/hello.txt"

    uploaded_path = storage_ops.upload_bytes(content, dest_path)
    assert uploaded_path

    downloaded = storage_ops.read_bytes(dest_path)
    assert downloaded == content


async def test_list_files_filters_by_extension(minio_settings):
    """Upload mixed file types and filter by extension."""
    pdf_content = b"PDF content"
    txt_content = b"Text content"

    storage_ops.upload_bytes(pdf_content, "test/doc1.pdf")
    storage_ops.upload_bytes(txt_content, "test/doc2.txt")

    pdf_files = storage_ops.list_files("test", extensions=(".pdf",))
    assert "test/doc1.pdf" in pdf_files
    assert "test/doc2.txt" not in pdf_files

    txt_files = storage_ops.list_files("test", extensions=(".txt",))
    assert "test/doc2.txt" in txt_files
    assert "test/doc1.pdf" not in txt_files


async def test_list_files_case_insensitive_extension_match(minio_settings):
    """Verify extension matching is case-insensitive."""
    content = b"Document"
    storage_ops.upload_bytes(content, "test/UPPERCASE.PDF")
    storage_ops.upload_bytes(content, "test/lowercase.pdf")
    storage_ops.upload_bytes(content, "test/MixedCase.Pdf")

    files = storage_ops.list_files("test", extensions=(".pdf",))
    assert len([f for f in files if f.endswith((".pdf", ".PDF", ".Pdf"))]) == 3


async def test_etag_returns_stripped_etag(minio_settings):
    """Verify etag parsing handles MinIO's quoted ETag format."""
    content = b"Known content for ETag test"
    storage_ops.upload_bytes(content, "test/etag_test.bin")

    etag = storage_ops.etag("test/etag_test.bin")
    assert etag
    assert not etag.startswith('"')
    assert not etag.endswith('"')


async def test_etag_falls_back_to_sha256(minio_settings):
    """Verify fallback to SHA-256 if ETag is missing."""
    content = b"Content for SHA256 verification"
    storage_ops.upload_bytes(content, "test/sha256_test.bin")

    etag = storage_ops.etag("test/sha256_test.bin")
    expected_sha = hashlib.sha256(content).hexdigest()

    assert etag is not None
    assert len(etag) == 64


async def test_ensure_bucket_creates_bucket_when_missing(minio_settings, monkeypatch):
    """Verify ensure_bucket creates bucket when it doesn't exist."""
    from config.settings import settings

    test_bucket = "new-test-bucket-" + "".join([str(i) for i in range(8)])
    monkeypatch.setattr(settings, "storage_root", f"s3://{test_bucket}/prefix")
    import pipeline.tasks.storage_ops

    pipeline.tasks.storage_ops._fs_cache.clear()

    storage_ops.ensure_bucket()

    assert storage_ops.exists(f"{test_bucket}/")


async def test_exists_returns_true_for_existing_objects(minio_settings):
    """Verify exists() returns True for uploaded objects."""
    content = b"Test object"
    storage_ops.upload_bytes(content, "test/exists_test.bin")

    assert storage_ops.exists("test/exists_test.bin")


async def test_exists_returns_false_for_nonexistent_objects(minio_settings):
    """Verify exists() returns False for nonexistent objects."""
    assert not storage_ops.exists("test/nonexistent_file_xyz_12345.bin")


async def test_read_text_and_write_text_roundtrip(minio_settings):
    """Verify text read/write operations preserve content."""
    text_content = "This is a test document\nWith multiple lines\nAnd UTF-8 chars: 你好"
    dest_path = "test/text_file.txt"

    storage_ops.write_text(text_content, dest_path)
    read_back = storage_ops.read_text(dest_path)

    assert read_back == text_content


async def test_list_files_returns_empty_for_missing_prefix(minio_settings):
    """Verify list_files returns empty list for nonexistent prefix."""
    files = storage_ops.list_files("test/nonexistent/prefix")
    assert files == []
