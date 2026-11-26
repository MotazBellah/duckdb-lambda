import os

import duckdb

from duckdb_lambda_s3.resources.duckdb_res import DuckDBResource

duckdb_resource = DuckDBResource(
    memory_limit="1GB",
    temp_directory="/tmp/duckdb",
    threads=2,
)

LANDING_BUCKET = os.environ.get("LANDING_BUCKET", "duckdb-demo-landing")
STORES_KEY = os.environ.get("STORES_KEY", "stores.csv")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "duckdb-demo-staging")
STAGING_PREFIX = os.environ.get("STAGING_PREFIX", "stores/")


def convert_stores(con: duckdb.DuckDBPyConnection, source: str, destination: str) -> int:
    """Reads the stores CSV, converts WKT to a geometry and writes Parquet files
    into the `destination` directory (a local path or an s3:// URI).
    Returns the number of rows written.
    """
    return con.execute(f"""
        COPY (
            SELECT
                store_id,
                store_name,
                ST_GeomFromText(wkt) AS geom
            FROM read_csv_auto('{source}')
        ) TO '{destination}' (
            FORMAT PARQUET,
            OVERWRITE_OR_IGNORE,
            PER_THREAD_OUTPUT true,
            FILENAME_PATTERN 'stores_{{i}}',
            ROW_GROUP_SIZE 100_000
        )
    """).fetchone()[0]


def handler(event, context):
    """Converts landing/stores.csv to Parquet in the staging bucket.

    DuckDB reads the CSV straight from S3 and writes the Parquet files straight
    to the staging bucket: nothing is downloaded to the Lambda.

    The event is ignored, so invoke it directly.
    """
    source = f"s3://{LANDING_BUCKET}/{STORES_KEY}"
    destination = f"s3://{STAGING_BUCKET}/{STAGING_PREFIX.strip('/')}"

    with duckdb_resource.open_database("stores.duckdb") as con:
        rows = convert_stores(con, source, destination)

    return {"source": source, "output": destination, "rows": rows}
