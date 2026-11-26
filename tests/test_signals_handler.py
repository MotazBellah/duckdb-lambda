import gzip

import duckdb
import pytest

from duckdb_lambda_s3.resources.duckdb_res import DuckDBResource
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
def con(tmp_path):
    """Real DuckDB with spatial loaded, working on local files (no S3)."""
    resource = DuckDBResource(
        temp_directory=str(tmp_path / "duckdb"), memory_limit="512MB", threads=2
    )
    with resource.open_database("test.duckdb") as connection:
        yield connection


@pytest.fixture
def raw_dir(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for name, content in {"part_1": PART_1, "part_2": PART_2}.items():
        with gzip.open(raw / f"{name}.csv.gz", "wt") as f:
            f.write(content)
    (raw / "readme.txt").write_text("not a signal part")  # must be ignored by the glob
    return raw


def test_converts_all_parts_to_parquet(con, raw_dir, tmp_path):
    out_dir = tmp_path / "out"

    rows_written = handler_module.convert_signals(
        con, f"{raw_dir}/*.csv.gz", str(out_dir)
    )

    assert rows_written == 3
    # PER_THREAD_OUTPUT: the number of files depends on how many threads got data.
    assert len(list(out_dir.glob("signals_*.parquet"))) >= 1

    columns = [
        r[0]
        for r in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{out_dir}/*.parquet')"
        ).fetchall()
    ]
    rows = con.execute(
        f"""
        SELECT device_id, date, ST_X(geom), ST_Y(geom)
        FROM read_parquet('{out_dir}/*.parquet')
        ORDER BY device_id
        """
    ).fetchall()

    # The unnamed index column is dropped, the derived columns are added.
    assert columns == ["device_id", "lat", "lon", "utc_timestamp", "date", "geom"]
    assert rows == [
        (1, "2021-01-01", 13.4, 52.5),
        (2, "2021-01-02", 13.3, 52.6),
        (3, "2021-01-01", 13.2, 52.7),
    ]


def test_raises_when_no_parts_match(con, tmp_path):
    with pytest.raises(duckdb.IOException):
        handler_module.convert_signals(
            con, f"{tmp_path}/nothing_here/*.csv.gz", str(tmp_path / "out")
        )
