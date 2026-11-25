import os
import tempfile
from pathlib import Path
from urllib.parse import unquote_plus

from duckdb_lambda_s3.resources.duckdb_res import DuckDBResource
from duckdb_lambda_s3.resources.s3_res import S3Resource

s3_resource = S3Resource()
duckdb_resource = DuckDBResource(
    memory_limit="1GB",
    temp_directory="/tmp/duckdb",
    threads=2,
)

STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "duckdb-demo-staging")
STAGING_PREFIX = os.environ.get("STAGING_PREFIX", "stores/")


def handler(event, context):
    """Triggered by an S3 ObjectCreated event for stores.csv in the landing bucket.

    Downloads the CSV, converts the WKT column to a geometry, writes Parquet
    (a directory of files, one per thread) and uploads them under the staging
    prefix.
    """
    record = event["Records"][0]["s3"]
    bucket = record["bucket"]["name"]
    key = unquote_plus(record["object"]["key"])  # S3 event keys are URL-encoded

    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        stores_csv = s3_resource.download(bucket, key, str(Path(tmp) / "stores.csv"))
        out_dir = Path(tmp) / "out"  # PER_THREAD_OUTPUT writes a directory

        with duckdb_resource.open_database("stores.duckdb") as con:
            con.execute(f"""
                COPY (
                    SELECT
                        store_id,
                        store_name,
                        ST_GeomFromText(wkt) AS geom
                    FROM read_csv_auto('{stores_csv}')
                ) TO '{out_dir}' (
                    FORMAT PARQUET,
                    OVERWRITE_OR_IGNORE,
                    PER_THREAD_OUTPUT true,
                    FILENAME_PATTERN 'stores_{{i}}',
                    ROW_GROUP_SIZE 100_000
                )
            """)

        outputs = [
            s3_resource.upload(str(f), STAGING_BUCKET, f"{STAGING_PREFIX}{f.name}")
            for f in sorted(out_dir.glob("*.parquet"))
        ]

    return {"source": f"s3://{bucket}/{key}", "outputs": outputs}
