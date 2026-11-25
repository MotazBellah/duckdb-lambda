import shutil
from pathlib import Path

import pytest

from duckdb_lambda_s3.matched_signals import matched_signals_handler as handler_module

# Two 0.1 x 0.1 degree squares.
STORES = [
    ("place_1", "McDonald's", "POLYGON ((13.0 52.0, 13.1 52.0, 13.1 52.1, 13.0 52.1, 13.0 52.0))"),
    ("place_2", "Aldi", "POLYGON ((13.2 52.2, 13.3 52.2, 13.3 52.3, 13.2 52.3, 13.2 52.2))"),
]
# (device_id, date, lon, lat)
SIGNALS = [
    (1, "2021-01-01", 13.05, 52.05),  # inside place_1
    (2, "2021-01-01", 14.00, 53.00),  # outside every store
    (3, "2021-01-02", 13.00, 52.05),  # exactly on place_1's edge
    (4, "2021-01-02", 13.25, 52.25),  # inside place_2
]


def write_parquet(con, select_sql: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({select_sql}) TO '{path}' (FORMAT PARQUET)")


@pytest.fixture
def fake_s3(tmp_path, monkeypatch):
    """Fakes S3 with local folders: <tmp>/s3/<bucket>/<key>."""
    monkeypatch.setattr(
        handler_module.duckdb_resource, "temp_directory", str(tmp_path / "duckdb")
    )
    staging = tmp_path / "s3" / "test-staging"

    # Build the input parquet files the same way the stores/signals handlers do.
    con = handler_module.duckdb_resource.connect("fixtures.duckdb")
    try:
        stores_values = ", ".join(f"('{i}', '{n.replace(chr(39), chr(39) * 2)}', '{w}')" for i, n, w in STORES)
        write_parquet(
            con,
            f"SELECT store_id, store_name, ST_GeomFromText(wkt) AS geom "
            f"FROM (VALUES {stores_values}) t(store_id, store_name, wkt)",
            staging / "stores" / "stores.parquet",
        )
        signals_values = ", ".join(f"({d}, '{dt}', {lon}, {lat})" for d, dt, lon, lat in SIGNALS)
        write_parquet(
            con,
            f"SELECT device_id, date, ST_Point(lon, lat) AS geom "
            f"FROM (VALUES {signals_values}) t(device_id, date, lon, lat)",
            staging / "signals" / "signals.parquet",
        )
    finally:
        con.close()

    uploaded = tmp_path / "uploaded"
    uploaded.mkdir()
    calls = {"uploads": []}

    def fake_download_prefix(bucket, prefix, local_dir):
        files = list((tmp_path / "s3" / bucket / prefix).glob("*"))
        if not files:
            raise FileNotFoundError(f"No objects under s3://{bucket}/{prefix}")
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy(f, Path(local_dir) / f.name)
        return local_dir

    def fake_upload(local_path, bucket, key):
        # The handler deletes its temp dir on return, so copy the file now.
        target = uploaded / Path(key).name
        shutil.copy(local_path, target)
        calls["uploads"].append((bucket, key, target))
        return f"s3://{bucket}/{key}"

    monkeypatch.setattr(handler_module.s3_resource, "download_prefix", fake_download_prefix)
    monkeypatch.setattr(handler_module.s3_resource, "upload", fake_upload)
    monkeypatch.setattr(handler_module, "STAGING_BUCKET", "test-staging")
    monkeypatch.setattr(handler_module, "STORES_PREFIX", "stores")
    monkeypatch.setattr(handler_module, "SIGNALS_PREFIX", "signals")
    monkeypatch.setattr(handler_module, "CURATED_BUCKET", "test-curated")
    monkeypatch.setattr(handler_module, "CURATED_KEY", "matched_signals/matched_signals.parquet")
    return calls


def test_matches_signals_to_stores_and_uploads_to_curated(fake_s3):
    result = handler_module.handler({}, None)

    assert len(fake_s3["uploads"]) == 1
    bucket, key, parquet_path = fake_s3["uploads"][0]
    assert (bucket, key) == ("test-curated", "matched_signals/matched_signals.parquet")
    assert result == {
        "matches": 3,
        "output": "s3://test-curated/matched_signals/matched_signals.parquet",
    }

    con = handler_module.duckdb_resource.connect("verify.duckdb")
    try:
        rows = con.execute(
            f"""
            SELECT device_id, date, store_id, store_name
            FROM read_parquet('{parquet_path}')
            ORDER BY device_id
            """
        ).fetchall()
    finally:
        con.close()

    # Device 2 is outside every store, so it is dropped.
    # Device 3 sits on the edge: ST_Intersects counts it as a match.
    assert rows == [
        (1, "2021-01-01", "place_1", "McDonald's"),
        (3, "2021-01-02", "place_1", "McDonald's"),
        (4, "2021-01-02", "place_2", "Aldi"),
    ]


def test_raises_when_staging_input_is_missing(fake_s3, monkeypatch):
    monkeypatch.setattr(handler_module, "SIGNALS_PREFIX", "does_not_exist")

    with pytest.raises(FileNotFoundError):
        handler_module.handler({}, None)

    assert fake_s3["uploads"] == []
