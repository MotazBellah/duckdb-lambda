import pytest


@pytest.fixture(autouse=True)
def s3_env(monkeypatch):
    """DuckDBResource.connect() reads these to build the S3 secret.
    The tests only use local files, so dummy values are enough."""
    monkeypatch.setenv("S3_KEY_ID", "test")
    monkeypatch.setenv("S3_SECRET", "test")
    monkeypatch.setenv("S3_REGION", "us-east-1")
