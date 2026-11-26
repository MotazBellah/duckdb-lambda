import pytest

from duckdb_lambda_s3.resources.duckdb_res import DuckDBResource
from duckdb_lambda_s3.stores import stores_hanlder as handler_module

STORES_CSV = """store_id,store_name,wkt
place_1,McDonald's,"POLYGON ((13.0 52.0, 13.1 52.0, 13.1 52.1, 13.0 52.1, 13.0 52.0))"
place_2,Aldi,"POLYGON ((13.2 52.2, 13.3 52.2, 13.3 52.3, 13.2 52.3, 13.2 52.2))"
"""


@pytest.fixture
def con(tmp_path):
    """Real DuckDB with spatial loaded, working on local files (no S3)."""
    resource = DuckDBResource(
        temp_directory=str(tmp_path / "duckdb"), memory_limit="512MB", threads=2
    )
    with resource.open_database("test.duckdb") as connection:
        yield connection


def test_converts_csv_to_parquet_files(con, tmp_path):
    source = tmp_path / "stores.csv"
    source.write_text(STORES_CSV)
    out_dir = tmp_path / "out"

    rows_written = handler_module.convert_stores(con, str(source), str(out_dir))

    assert rows_written == 2
    # PER_THREAD_OUTPUT: the number of files depends on the threads used.
    files = sorted(out_dir.glob("stores_*.parquet"))
    assert len(files) >= 1

    rows = con.execute(
        f"""
        SELECT store_id, store_name, ST_GeometryType(geom)::VARCHAR, ST_Area(geom)
        FROM read_parquet('{out_dir}/*.parquet')
        ORDER BY store_id
        """
    ).fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("place_1", "McDonald's", "POLYGON"),
        ("place_2", "Aldi", "POLYGON"),
    ]
    assert rows[0][3] == pytest.approx(0.01)  # 0.1 x 0.1 degree square


def test_raises_when_csv_is_missing_required_column(con, tmp_path):
    source = tmp_path / "bad.csv"
    source.write_text("store_id,store_name\nplace_1,Aldi\n")

    with pytest.raises(Exception):
        handler_module.convert_stores(con, str(source), str(tmp_path / "out"))

    assert not list((tmp_path / "out").glob("*.parquet"))


def test_handler_builds_s3_uris_from_config(con, monkeypatch):
    calls = []

    def fake_convert(connection, source, destination):
        calls.append((source, destination))
        return 247

    class FakeResource:
        def open_database(self, name):
            from contextlib import nullcontext

            return nullcontext(con)

    monkeypatch.setattr(handler_module, "convert_stores", fake_convert)
    monkeypatch.setattr(handler_module, "duckdb_resource", FakeResource())
    monkeypatch.setattr(handler_module, "LANDING_BUCKET", "test-landing")
    monkeypatch.setattr(handler_module, "STORES_KEY", "stores.csv")
    monkeypatch.setattr(handler_module, "STAGING_BUCKET", "test-staging")
    monkeypatch.setattr(handler_module, "STAGING_PREFIX", "stores/")

    result = handler_module.handler({}, None)  # the event is ignored

    assert calls == [("s3://test-landing/stores.csv", "s3://test-staging/stores")]
    assert result == {
        "source": "s3://test-landing/stores.csv",
        "output": "s3://test-staging/stores",
        "rows": 247,
    }
