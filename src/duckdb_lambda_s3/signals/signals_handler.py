import os
import tempfile
from pathlib import Path

from duckdb_lambda_s3.resources.duckdb_res import DuckDBResource
from duckdb_lambda_s3.resources.s3_res import S3Resource

s3_resource = S3Resource()
# Tunable per deployment so the memory scenario can be reproduced from Terraform.
# Keep DUCKDB_MEMORY_LIMIT below the Lambda memory size.
duckdb_resource = DuckDBResource(
    memory_limit=os.environ.get("DUCKDB_MEMORY_LIMIT", "3GB"),
    temp_directory="/tmp/duckdb",
    threads=int(os.environ.get("DUCKDB_THREADS", "2")),
)
# Rows each writer thread buffers before it flushes a Parquet row group.
ROW_GROUP_SIZE = int(os.environ.get("ROW_GROUP_SIZE", "100000"))
# Bytes the CSV reader buffers per open file and thread (DuckDB default: 32000000).
# A smaller buffer lowers the memory floor of the read. All parts share one schema,
# so union_by_name is not needed.
CSV_BUFFER_SIZE = int(os.environ.get("CSV_BUFFER_SIZE", "4194304"))

LANDING_BUCKET = os.environ.get("LANDING_BUCKET", "duckdb-demo-landing")
SIGNALS_PREFIX = os.environ.get("SIGNALS_PREFIX", "signal_data/")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "duckdb-demo-staging")
STAGING_PREFIX = os.environ.get("STAGING_PREFIX", "signals/")


def handler(event, context):
    """Converts every signal part (*.csv.gz) under the landing prefix to Parquet
    and uploads the result to the staging bucket.

    Output is written in parallel (PER_THREAD_OUTPUT): one file per thread that
    received data, uploaded under the staging prefix.

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
        out_dir = Path(tmp) / "out"  # PER_THREAD_OUTPUT writes a directory

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
                    FROM read_csv('{signals_glob}', buffer_size={CSV_BUFFER_SIZE})
                ) TO '{out_dir}' (
                    FORMAT PARQUET,
                    OVERWRITE_OR_IGNORE,
                    PER_THREAD_OUTPUT true,
                    FILENAME_PATTERN 'signals_{{i}}',
                    ROW_GROUP_SIZE {ROW_GROUP_SIZE}
                )
            """)

        outputs = [
            s3_resource.upload(str(f), STAGING_BUCKET, f"{STAGING_PREFIX}{f.name}")
            for f in sorted(out_dir.glob("*.parquet"))
        ]

    return {"parts": len(keys), "outputs": outputs}
