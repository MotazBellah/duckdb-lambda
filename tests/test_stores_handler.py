import shutil
from pathlib import Path

import pytest

from duckdb_lambda_s3.stores import stores_hanlder as handler_module

STORES_CSV = """store_id,store_name,wkt
place_1,McDonald's,"POLYGON ((13.0 52.0, 13.1 52.0, 13.1 52.1, 13.0 52.1, 13.0 52.0))"
place_2,Aldi,"POLYGON ((13.2 52.2, 13.3 52.2, 13.3 52.3, 13.2 52.3, 13.2 52.2))"
"""


def make_event(bucket: str, key: str) -> dict:
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


@pytest.fixture
def fake_s3(tmp_path, monkeypatch):
    """Replaces S3 with the local filesystem and records what the handler does."""
    calls = {"downloads": [], "uploads": []}
    source = tmp_path / "source_stores.csv"
    source.write_text(STORES_CSV)
    uploaded = tmp_path / "uploaded"
    uploaded.mkdir()

    def fake_download(bucket, key, local_path):
        calls["downloads"].append((bucket, key))
        shutil.copy(source, local_path)
        return local_path

    def fake_upload(local_path, bucket, key):
        # The handler deletes its temp dir on return, so copy the file now.
        target = uploaded / Path(key).name
        shutil.copy(local_path, target)
        calls["uploads"].append((bucket, key, target))
        return f"s3://{bucket}/{key}"

    monkeypatch.setattr(handler_module.s3_resource, "download", fake_download)
    monkeypatch.setattr(handler_module.s3_resource, "upload", fake_upload)
    # Keep DuckDB's spill/db files inside pytest's tmp dir, not /tmp/duckdb.
    monkeypatch.setattr(
        handler_module.duckdb_resource, "temp_directory", str(tmp_path / "duckdb")
    )
    monkeypatch.setattr(handler_module, "STAGING_BUCKET", "test-staging")
    monkeypatch.setattr(handler_module, "STAGING_KEY", "stores/stores.parquet")
    return calls


def test_converts_csv_to_parquet_and_uploads_to_staging(fake_s3):
    result = handler_module.handler(make_event("test-landing", "stores.csv"), None)

    assert fake_s3["downloads"] == [("test-landing", "stores.csv")]
    assert len(fake_s3["uploads"]) == 1
    bucket, key, parquet_path = fake_s3["uploads"][0]
    assert (bucket, key) == ("test-staging", "stores/stores.parquet")
    assert result == {
        "source": "s3://test-landing/stores.csv",
        "output": "s3://test-staging/stores/stores.parquet",
    }

    # connect() loads the spatial extension, so ST_* functions work here.
    con = handler_module.duckdb_resource.connect("verify.duckdb")
    try:
        rows = con.execute(
            f"""
            SELECT store_id, store_name, ST_GeometryType(geom)::VARCHAR, ST_Area(geom)
            FROM read_parquet('{parquet_path}')
            ORDER BY store_id
            """
        ).fetchall()
    finally:
        con.close()

    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("place_1", "McDonald's", "POLYGON"),
        ("place_2", "Aldi", "POLYGON"),
    ]
    assert rows[0][3] == pytest.approx(0.01)  # 0.1 x 0.1 degree square


def test_decodes_url_encoded_s3_key(fake_s3):
    handler_module.handler(make_event("test-landing", "raw/my+stores.csv"), None)

    assert fake_s3["downloads"] == [("test-landing", "raw/my stores.csv")]


def test_raises_when_csv_is_missing_required_column(fake_s3, monkeypatch, tmp_path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("store_id,store_name\nplace_1,Aldi\n")

    def fake_download(bucket, key, local_path):
        shutil.copy(bad_csv, local_path)
        return local_path

    monkeypatch.setattr(handler_module.s3_resource, "download", fake_download)

    with pytest.raises(Exception):
        handler_module.handler(make_event("test-landing", "stores.csv"), None)

    assert fake_s3["uploads"] == []  # nothing is uploaded on failure
