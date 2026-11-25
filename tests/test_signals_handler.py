import gzip
import shutil
from pathlib import Path

import pytest

from duckdb_lambda_s3.signals import signals_handler as handler_module

# Same layout as the real data: an unnamed pandas index column comes first.
PART_1 = """,device_id,lat,lon,utc_timestamp
0,1,52.5,13.4,1609504332000
1,2,52.6,13.3,1609590732000
"""
PART_2 = """,device_id,lat,lon,utc_timestamp
0,3,52.7,13.2,1609504332000
"""


@pytest.fixture
def fake_s3(tmp_path, monkeypatch):
    """Replaces S3 with local files and records the handler's uploads."""
    parts = {}
    for name, content in {"part_1": PART_1, "part_2": PART_2}.items():
        path = tmp_path / f"{name}.csv.gz"
        with gzip.open(path, "wt") as f:
            f.write(content)
        parts[f"signal_data/{name}.csv.gz"] = path
    parts["signal_data/readme.txt"] = tmp_path / "readme.txt"  # must be ignored
    parts["signal_data/readme.txt"].write_text("not a signal part")

    uploaded = tmp_path / "uploaded"
    uploaded.mkdir()
    calls = {"downloads": [], "uploads": []}

    def fake_list_keys(bucket, prefix):
        return [k for k in parts if k.startswith(prefix)]

    def fake_download(bucket, key, local_path):
        calls["downloads"].append(key)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(parts[key], local_path)
        return local_path

    def fake_upload(local_path, bucket, key):
        # The handler deletes its temp dir on return, so copy the file now.
        target = uploaded / Path(key).name
        shutil.copy(local_path, target)
        calls["uploads"].append((bucket, key, target))
        return f"s3://{bucket}/{key}"

    s3 = handler_module.s3_resource
    monkeypatch.setattr(s3, "list_keys", fake_list_keys)
    monkeypatch.setattr(s3, "download", fake_download)
    monkeypatch.setattr(s3, "upload", fake_upload)
    monkeypatch.setattr(
        handler_module.duckdb_resource, "temp_directory", str(tmp_path / "duckdb")
    )
    monkeypatch.setattr(handler_module, "LANDING_BUCKET", "test-landing")
    monkeypatch.setattr(handler_module, "SIGNALS_PREFIX", "signal_data/")
    monkeypatch.setattr(handler_module, "STAGING_BUCKET", "test-staging")
    monkeypatch.setattr(handler_module, "STAGING_PREFIX", "signals/")
    return calls


def test_converts_all_parts_to_parquet_under_staging_prefix(fake_s3):
    result = handler_module.handler({}, None)

    # Only the .csv.gz parts are downloaded, the readme is skipped.
    assert sorted(fake_s3["downloads"]) == [
        "signal_data/part_1.csv.gz",
        "signal_data/part_2.csv.gz",
    ]
    # PER_THREAD_OUTPUT: the number of files depends on how many threads got
    # data, so only check that every file lands under the staging prefix.
    assert len(fake_s3["uploads"]) >= 1
    for bucket, key, _ in fake_s3["uploads"]:
        assert bucket == "test-staging"
        assert key.startswith("signals/signals_") and key.endswith(".parquet")
    assert result["parts"] == 2
    assert result["outputs"] == [
        f"s3://test-staging/{key}" for _, key, _ in fake_s3["uploads"]
    ]
    parquet_glob = str(fake_s3["uploads"][0][2].parent / "*.parquet")

    # connect() loads the spatial extension, so ST_* functions work here.
    con = handler_module.duckdb_resource.connect("verify.duckdb")
    try:
        columns = [
            r[0]
            for r in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{parquet_glob}')"
            ).fetchall()
        ]
        rows = con.execute(
            f"""
            SELECT device_id, date, ST_X(geom), ST_Y(geom)
            FROM read_parquet('{parquet_glob}')
            ORDER BY device_id
            """
        ).fetchall()
    finally:
        con.close()

    # The unnamed index column is dropped, the derived columns are added.
    assert columns == ["device_id", "lat", "lon", "utc_timestamp", "date", "geom"]
    assert rows == [
        (1, "2021-01-01", 13.4, 52.5),
        (2, "2021-01-02", 13.3, 52.6),
        (3, "2021-01-01", 13.2, 52.7),
    ]


def test_raises_when_no_parts_found(fake_s3, monkeypatch):
    monkeypatch.setattr(handler_module.s3_resource, "list_keys", lambda b, p: [])

    with pytest.raises(FileNotFoundError):
        handler_module.handler({}, None)

    assert fake_s3["uploads"] == []
