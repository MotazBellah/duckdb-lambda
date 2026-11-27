import os

import duckdb

from duckdb_lambda_s3.resources.duckdb_res import DuckDBResource

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


def convert_signals(
    con: duckdb.DuckDBPyConnection,
    source_glob: str,
    destination: str,
    row_group_size: int = ROW_GROUP_SIZE,
    csv_buffer_size: int = CSV_BUFFER_SIZE,
) -> int:
    """Reads the signal CSV parts matching `source_glob`, adds a date column and a
    point geometry, and writes a single Parquet file to `destination`
    (local file path or s3:// URI ending in .parquet). Returns the number of rows written.
    """
    # The CSV's first column is an unnamed pandas index: we skip it by
    # selecting only the columns we need.
    return con.execute(f"""
        COPY (
            SELECT
                device_id,
                lat,
                lon,
                utc_timestamp,
                strftime(to_timestamp(utc_timestamp / 1000), '%Y-%m-%d') AS date,
                ST_Point(lon, lat) AS geom
            FROM read_csv('{source_glob}', buffer_size={csv_buffer_size})
        ) TO '{destination}' (
            FORMAT PARQUET,
            OVERWRITE_OR_IGNORE,
            PER_THREAD_OUTPUT true,
            FILENAME_PATTERN 'signals_{{i}}',
            ROW_GROUP_SIZE {row_group_size}
        )
    """).fetchone()[0]


def handler(event, context):
    """Converts every signal part (*.csv.gz) under the landing prefix to Parquet.
    """
    source_glob = f"s3://{LANDING_BUCKET}/{SIGNALS_PREFIX.strip('/')}/*.csv.gz"
    # Without PER_THREAD_OUTPUT, COPY TO writes exactly one file at this path,
    # so it must be a full object key, not a "folder".
    # destination = f"s3://{STAGING_BUCKET}/{STAGING_PREFIX.strip('/')}/signals.parquet"
    destination = f"s3://{STAGING_BUCKET}/{STAGING_PREFIX.strip('/')}"

    with duckdb_resource.open_database("signals.duckdb") as con:
        rows = convert_signals(con, source_glob, destination)

    return {"source": source_glob, "output": destination, "rows": rows}
