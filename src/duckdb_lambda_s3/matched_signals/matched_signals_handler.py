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

STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "duckdb-demo-staging")
STORES_PREFIX = os.environ.get("STORES_PREFIX", "stores/")
SIGNALS_PREFIX = os.environ.get("SIGNALS_PREFIX", "signals/")
CURATED_BUCKET = os.environ.get("CURATED_BUCKET", "duckdb-demo-curated")
CURATED_KEY = os.environ.get(
    "CURATED_KEY", "matched_signals/matched_signals.parquet"
)


def handler(event, context):
    """Finds which signals fall inside which store and writes the matches.

    Reads the stores and signals Parquet files from the staging bucket, joins
    them with ST_Intersects and uploads ONE Parquet file to the curated bucket.
    The event is ignored, so invoke it directly.
    """
    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        stores_path = s3_resource.download_prefix(
            STAGING_BUCKET, STORES_PREFIX, str(Path(tmp) / "in" / "stores")
        )
        signals_path = s3_resource.download_prefix(
            STAGING_BUCKET, SIGNALS_PREFIX, str(Path(tmp) / "in" / "signals")
        )

        out_dir = Path(tmp) / "out"
        out_dir.mkdir()
        out_file = out_dir / "matched_signals.parquet"

        with duckdb_resource.open_database("matched_signals.duckdb") as con:
            con.execute(f"""
                CREATE OR REPLACE TABLE stores AS
                SELECT store_id, store_name, geom
                FROM read_parquet('{stores_path}/*.parquet')
            """)
            con.execute(f"""
                CREATE OR REPLACE TABLE signals AS
                SELECT device_id, date, geom
                FROM read_parquet('{signals_path}/*.parquet')
            """)
            con.execute(f"""
                COPY (
                    SELECT
                        sig.device_id,
                        sig.date,
                        st.store_id,
                        st.store_name
                    FROM signals sig
                    JOIN stores st
                      ON ST_Intersects(sig.geom, st.geom)
                ) TO '{out_file}' (FORMAT PARQUET)
            """)
            matches = con.execute(
                f"SELECT count(*) FROM read_parquet('{out_file}')"
            ).fetchone()[0]

        uri = s3_resource.upload(str(out_file), CURATED_BUCKET, CURATED_KEY)

    return {"matches": matches, "output": uri}
