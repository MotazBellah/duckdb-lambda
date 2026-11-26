import pytest

from duckdb_lambda_s3.matched_signals import matched_signals_handler as handler_module
from duckdb_lambda_s3.resources.duckdb_res import DuckDBResource

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


@pytest.fixture
def con(tmp_path):
    """Real DuckDB with spatial loaded, working on local files (no S3)."""
    resource = DuckDBResource(
        temp_directory=str(tmp_path / "duckdb"), memory_limit="512MB", threads=2
    )
    with resource.open_database("test.duckdb") as connection:
        yield connection


@pytest.fixture
def staging(con, tmp_path):
    """Builds the input parquet files the same way the stores/signals handlers do."""
    stores_dir = tmp_path / "staging" / "stores"
    signals_dir = tmp_path / "staging" / "signals"
    stores_dir.mkdir(parents=True)
    signals_dir.mkdir(parents=True)

    stores_values = ", ".join(
        "('{}', '{}', '{}')".format(i, n.replace("'", "''"), w) for i, n, w in STORES
    )
    con.execute(
        f"""
        COPY (
            SELECT store_id, store_name, ST_GeomFromText(wkt) AS geom
            FROM (VALUES {stores_values}) t(store_id, store_name, wkt)
        ) TO '{stores_dir}/stores_0.parquet' (FORMAT PARQUET)
        """
    )
    signals_values = ", ".join(
        f"({d}, '{dt}', {lon}, {lat})" for d, dt, lon, lat in SIGNALS
    )
    con.execute(
        f"""
        COPY (
            SELECT device_id, date, ST_Point(lon, lat) AS geom
            FROM (VALUES {signals_values}) t(device_id, date, lon, lat)
        ) TO '{signals_dir}/signals_0.parquet' (FORMAT PARQUET)
        """
    )
    return stores_dir, signals_dir


def test_matches_signals_to_stores(con, staging, tmp_path):
    stores_dir, signals_dir = staging
    output = tmp_path / "curated" / "matched_signals.parquet"
    output.parent.mkdir()

    matches = handler_module.match_signals(
        con, f"{stores_dir}/*.parquet", f"{signals_dir}/*.parquet", str(output)
    )

    assert matches == 3
    rows = con.execute(
        f"""
        SELECT device_id, date, store_id, store_name
        FROM read_parquet('{output}')
        ORDER BY device_id
        """
    ).fetchall()
    # Device 2 is outside every store, so it is dropped.
    # Device 3 sits on the edge: ST_Intersects counts it as a match.
    assert rows == [
        (1, "2021-01-01", "place_1", "McDonald's"),
        (3, "2021-01-02", "place_1", "McDonald's"),
        (4, "2021-01-02", "place_2", "Aldi"),
    ]


def test_raises_when_staging_input_is_missing(con, staging, tmp_path):
    stores_dir, _ = staging
    output = tmp_path / "curated" / "matched_signals.parquet"
    output.parent.mkdir()

    with pytest.raises(Exception):
        handler_module.match_signals(
            con, f"{stores_dir}/*.parquet", f"{tmp_path}/missing/*.parquet", str(output)
        )

    assert not output.exists()  # nothing is written on failure
