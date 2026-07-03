"""Unit tests for config/settings.py and config/logging.py."""
import logging
import pytest
from config.settings import Settings
from config.logging import get_logger, configure_logging


class TestSettingsProperties:
    """Tests for Settings property methods."""

    def test_is_minio_true_for_s3_root(self):
        """Verify is_minio returns True for s3:// URLs."""
        settings = Settings(storage_root="s3://my-bucket/prefix")
        assert settings.is_minio is True

    def test_is_minio_false_for_file_root(self):
        """Verify is_minio returns False for file:// URLs."""
        settings = Settings(storage_root="file:///tmp/data")
        assert settings.is_minio is False

    def test_is_minio_false_for_default_root(self):
        """Verify is_minio returns False for default file:// root."""
        settings = Settings()
        assert settings.is_minio is False

    def test_storage_bucket_extracts_bucket_name(self):
        """Verify storage_bucket extracts the bucket name from s3 URL."""
        settings = Settings(storage_root="s3://my-test-bucket/some/prefix/path")
        assert settings.storage_bucket == "my-test-bucket"

    def test_storage_bucket_empty_for_non_s3_root(self):
        """Verify storage_bucket returns empty string for non-s3 URLs."""
        settings = Settings(storage_root="file:///tmp/data")
        assert settings.storage_bucket == ""

    def test_storage_bucket_handles_bucket_only(self):
        """Verify storage_bucket handles s3:// URL with just bucket name."""
        settings = Settings(storage_root="s3://bucket-name")
        assert settings.storage_bucket == "bucket-name"

    def test_storage_bucket_with_trailing_slash(self):
        """Verify storage_bucket handles trailing slash correctly."""
        settings = Settings(storage_root="s3://bucket-name/")
        assert settings.storage_bucket == "bucket-name"


class TestConfigureLogging:
    """Tests for configure_logging function."""

    def test_configure_logging_json_mode(self, monkeypatch):
        """Verify configure_logging works in json mode."""
        from config import logging as logging_module
        from config.settings import settings

        monkeypatch.setattr(settings, "log_format", "json")
        monkeypatch.setattr(settings, "log_level", "INFO")

        configure_logging()

        root_logger = logging.getLogger()
        assert len(root_logger.handlers) > 0

        logging.getLogger().handlers.clear()

    def test_configure_logging_console_mode(self, monkeypatch):
        """Verify configure_logging works in console mode."""
        from config import logging as logging_module
        from config.settings import settings

        monkeypatch.setattr(settings, "log_format", "console")
        monkeypatch.setattr(settings, "log_level", "INFO")

        configure_logging()

        root_logger = logging.getLogger()
        assert len(root_logger.handlers) > 0

        logging.getLogger().handlers.clear()

    def test_configure_logging_sets_log_level(self, monkeypatch):
        """Verify configure_logging sets the correct log level."""
        from config.settings import settings

        monkeypatch.setattr(settings, "log_format", "json")
        monkeypatch.setattr(settings, "log_level", "DEBUG")

        configure_logging()

        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

        logging.getLogger().handlers.clear()

    def test_get_logger_returns_structlog_logger(self):
        """Verify get_logger returns a structlog logger instance."""
        logger = get_logger("test.module")
        assert logger is not None
        assert hasattr(logger, "bind")
        assert hasattr(logger, "unbind")

    def test_get_logger_with_different_names(self):
        """Verify get_logger returns different instances for different names."""
        logger1 = get_logger("module.one")
        logger2 = get_logger("module.two")

        assert logger1 is not logger2
