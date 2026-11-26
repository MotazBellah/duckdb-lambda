import os

import duckdb

from duckdb_lambda_s3.resources.duckdb_res import DuckDBResource

duckdb_resource = DuckDBResource(
    memory_limit="3GB",
    temp_directory="/tmp/duckdb",
    threads=2,
)

STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "duckdb-demo-staging")
STORES_PREFIX = os.environ.get("STORES_PREFIX", "stores/")
SIGNALS_PREFIX = os.environ.get("SIGNALS_PREFIX", "signals/")
CURATED_BUCKET = os.environ.get("CURATED_BUCKET", "duckdb-demo-curated")
CURATED_KEY = os.environ.get(
    "CURATED_KEY", "matched_signals/matched_signals.parquet"
)


def match_signals(
    con: duckdb.DuckDBPyConnection,
    stores_glob: str,
    signals_glob: str,
    output_file: str,
) -> int:
    """Joins signals to the stores that contain them (ST_Intersects) and writes
    ONE Parquet file to `output_file` (local path or s3:// URI).
    Returns the number of matches written.
    """
    con.execute(f"""
        CREATE OR REPLACE TABLE stores AS
        SELECT store_id, store_name, geom
        FROM read_parquet('{stores_glob}')
    """)
    # Only these columns are fetched from S3: Parquet is read column by column.
    con.execute(f"""
        CREATE OR REPLACE TABLE signals AS
        SELECT device_id, date, geom
        FROM read_parquet('{signals_glob}')
    """)
    return con.execute(f"""
        COPY (
            SELECT
                sig.device_id,
                sig.date,
                st.store_id,
                st.store_name
            FROM signals sig
            JOIN stores st
              ON ST_Intersects(sig.geom, st.geom)
        ) TO '{output_file}' (FORMAT PARQUET)
    """).fetchone()[0]


def handler(event, context):
    """Finds which signals fall inside which store and writes the matches.

    DuckDB reads the stores and signals Parquet files straight from the staging
    bucket and writes ONE Parquet file straight to the curated bucket.
    The event is ignored, so invoke it directly.
    """
    stores_glob = f"s3://{STAGING_BUCKET}/{STORES_PREFIX.strip('/')}/*.parquet"
    signals_glob = f"s3://{STAGING_BUCKET}/{SIGNALS_PREFIX.strip('/')}/*.parquet"
    output_file = f"s3://{CURATED_BUCKET}/{CURATED_KEY}"

    with duckdb_resource.open_database("matched_signals.duckdb") as con:
        matches = match_signals(con, stores_glob, signals_glob, output_file)

    return {"matches": matches, "output": output_file}
