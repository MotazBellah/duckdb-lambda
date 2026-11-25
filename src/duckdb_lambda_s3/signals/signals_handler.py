import os
import tempfile
from pathlib import Path

from duckdb_lambda_s3.resources.duckdb_res import DuckDBResource
from duckdb_lambda_s3.resources.s3_res import S3Resource

s3_resource = S3Resource()
duckdb_resource = DuckDBResource(
    memory_limit="3GB",
    temp_directory="/tmp/duckdb",
    threads=2,
)

LANDING_BUCKET = os.environ.get("LANDING_BUCKET", "duckdb-demo-landing")
SIGNALS_PREFIX = os.environ.get("SIGNALS_PREFIX", "signal_data/")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "duckdb-demo-staging")
STAGING_KEY = os.environ.get("STAGING_KEY", "signals/signals.parquet")


def handler(event, context):
    """Merges every signal part (*.csv.gz) under the landing prefix into ONE
    Parquet file and uploads it to the staging bucket.

    The event is ignored, so invoke it directly instead of wiring an S3 trigger
    (a trigger would run it once per uploaded part).
    """
    keys = [
        k
        for k in s3_resource.list_keys(LANDING_BUCKET, SIGNALS_PREFIX)
        if k.endswith(".csv.gz")
    ]
    if not keys:
        raise FileNotFoundError(
            f"No .csv.gz files under s3://{LANDING_BUCKET}/{SIGNALS_PREFIX}"
        )

    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        raw_dir = Path(tmp) / "raw"
        for key in keys:
            s3_resource.download(LANDING_BUCKET, key, str(raw_dir / Path(key).name))
        signals_glob = raw_dir / "*.csv.gz"
        out_file = Path(tmp) / "signals.parquet"

        with duckdb_resource.open_database("signals.duckdb") as con:
            # The CSV's first column is an unnamed pandas index: we skip it by
            # selecting only the columns we need.
            con.execute(f"""
                COPY (
                    SELECT
                        device_id,
                        lat,
                        lon,
                        utc_timestamp,
                        strftime(to_timestamp(utc_timestamp / 1000), '%Y-%m-%d') AS date,
                        ST_Point(lon, lat) AS geom
                    FROM read_csv('{signals_glob}', union_by_name=true)
                ) TO '{out_file}' (FORMAT PARQUET)
            """)

        uri = s3_resource.upload(str(out_file), STAGING_BUCKET, STAGING_KEY)

    return {"parts": len(keys), "output": uri}
